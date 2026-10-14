# Deno — Tech Stack

What Deno is built with, why, and where each piece lives in the repo. Deployment:
[`09_FREE_DEPLOYMENT.md`](09_FREE_DEPLOYMENT.md). Variables: [`10_CONFIGURATION.md`](10_CONFIGURATION.md).
Design detail and ADRs: [`02_ARCHITECTURE.md`](02_ARCHITECTURE.md), [`08_DEVELOPMENT_PLAN.md`](08_DEVELOPMENT_PLAN.md).

## 1. At a glance

| Layer | Technology | Hosted on (prod) |
|---|---|---|
| Web app | Next.js 16, React 19, TypeScript, hand-written CSS (pixel-identical to the original design) | Vercel |
| Auth | Supabase Auth (email + password, Google OAuth, TOTP 2FA) via `@supabase/ssr` | Supabase |
| API | Python 3.12, FastAPI, Pydantic v2, uvicorn | Google Cloud Run |
| Agents | LangGraph `StateGraph` + LangChain (structured output, Postgres checkpointer) | Cloud Run Job |
| LLM | NVIDIA NIM (OpenAI-compatible): Nemotron 3 Super 120B, Llama 3.2 11B fallback, Nemotron embed + rerank | NVIDIA |
| Database | PostgreSQL + pgvector (`halfvec` 2048-d), SQLAlchemy 2 async + asyncpg, Alembic | Supabase |
| Cache / events / limits | Valkey / Redis (`redis[hiredis]`) | Upstash |
| Background jobs | taskiq (local/VPS) or Cloud Run Job executions (free deploy) | Cloud Run |
| Scheduled jobs | taskiq scheduler (local/VPS) or Cloud Scheduler → `/internal/cron/*` | Cloud Scheduler |
| Web search | SearXNG (self-hosted metasearch) | Cloud Run (private) |
| Scraping | httpx (HTTP/2), selectolax, defusedxml | — |
| Text analysis | NumPy (Burrows' Delta stylometry), regex anti-slop gates | — |
| Observability | structlog JSON logs, Prometheus metrics, Sentry, Langfuse | Cloud Logging |
| Billing (later) | Stripe | — |
| Tooling | uv workspace, ruff, mypy `--strict`, pytest, schemathesis, ESLint, tsc, Playwright visual diff | GitHub Actions |
| Containers | Docker multi-stage (uv, non-root uid 10001), BuildKit | Artifact Registry |

## 2. Repository layout

```
apps/
  api/      deno_api     FastAPI app: v1 routes (projects, runs, content, me, billing, takedowns),
                         Supabase JWT auth, SSE run stream, /internal/cron, /readyz, /metrics
  worker/   deno_worker  taskiq tasks + run_once.py (one job per Cloud Run Job execution)
packages/
  core/     deno_core    settings, logging, errors, DB session + models, jobs.enqueue, gcp.py, maintenance, rate limits
  gates/    deno_gates   anti-slop gates, density scorer, Ban Risk Score, stylometry (pure Python + NumPy)
  llm/      deno_llm     model router (fast/strong/judge + fallback), NIM limiter, LLM cache, Langfuse
  rag/      deno_rag     chunking, embeddings, rerank, retrieval over pgvector
  sources/  deno_sources keyless sources: Reddit, Hacker News, X syndication, LinkedIn public pages, RSS feeds; robots.txt checks
                         github.py / website.py: read the repo or product site an idea links to (intake);
                         website.py is SSRF-guarded (public IPs only, pinned connection, robots.txt, 1 MB cap)
  graphs/   deno_graphs  LangGraph graphs: validation/ (idea → verdict) and content/ (30-day plan)
web/                     Next.js app (app router): marketing, auth, /app workspace, account, legal
migrations/              Alembic migrations (0001 schema, 0002 seed data, 0003 profile fields)
deploy/                  cloudbuild-api.yaml, deploy-free.sh, searxng/Dockerfile
evals/                   retrieval and gate evaluation scripts
tests/                   unit, integration (local postgres-test only), live (NIM, opt-in)
Dockerfile               one backend image for API, worker, job and migrations
compose.dev.yml          local Valkey, SearXNG and postgres-test (+ optional api/worker/web)
compose.prod.yml         single-VPS alternative (Caddy TLS)
public/, gateway/        legacy static UI and Deno gateway, kept for the visual-diff baseline
```

## 3. Request paths

**Page load:** browser → Vercel (Next.js renders the page; `proxy.ts` refreshes the Supabase session cookie
and protects `/app`).

**API call:** browser → `https://deno-web-eight.vercel.app/api/v1/...` → Next.js rewrite (`BACKEND_URL`) →
Cloud Run `deno-api`. The browser sends `Authorization: Bearer <Supabase access token>`. FastAPI verifies it
against the project's JWKS and scopes every query to the token's `sub`. Users with 2FA must hold an `aal2` session.

**Validation run:** API → Cloud Run Admin API → `deno-run` execution → LangGraph graph:
query planning → parallel source fetches (SearXNG + keyless sources) → retrieval and rerank → adversarial agents →
verdict, TAM/SAM/SOM, competitors, communities. State is checkpointed in Postgres, so a retried
execution resumes. Progress events go to Redis and stream to the browser over SSE.

## 4. Key choices

- **Supabase for Postgres and Auth:** no auth code to maintain; pgvector built in; free tier.
- **LangGraph rather than ad-hoc scripts:** typed state, checkpoints and retries, parallel `Send` branches,
  and the same graph runs in a worker or a one-shot job.
- **NVIDIA NIM:** free trial key, OpenAI-compatible. The 40 req/min cap is enforced client-side through Redis.
- **Cloud Run Jobs instead of an always-on worker:** Cloud Run gives CPU only while it handles a request,
  and a polling worker would burn the Upstash free quota. One execution per run costs nothing while idle.
- **Same image everywhere:** API, job and migrations all use one Docker image, so code can't drift between them.
- **Tokyo region for everything:** Supabase, Upstash and Cloud Run sit side by side, which keeps database
  round trips short.

## 5. Local development

```bash
docker compose -f compose.dev.yml up -d valkey searxng       # local Redis + SearXNG (DB is hosted Supabase)
uv sync
uv run alembic upgrade head
uv run uvicorn deno_api.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker deno_worker.tasks:broker --workers 1    # runs the graphs locally (TASK_RUNNER=taskiq)
cd web && npm install && npm run dev                         # http://localhost:3000
```

Checks before pushing:
```bash
uv run ruff check . && uv run mypy && uv run pytest          # integration tests need: docker compose -f compose.dev.yml --profile test up -d postgres-test
cd web && npm run lint && npx tsc --noEmit && npm run build
```
