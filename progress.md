# Deno — Progress

**Last updated:** 2026-09-24
**Current work:** Flagship rebuild — `.claude/prds/deno-flagship.prd.md`, plan `docs/08_DEVELOPMENT_PLAN.md`
**Stack decisions (2026-09-24):** hosted Supabase Auth (no local containers) · Next.js 16 web client, pixel-identical to the v1 UI · LangGraph 1.2 + LangChain 1.x agents on NVIDIA NIM · Postgres + pgvector on the same Supabase project.

The v1 prototype (8-agent DAG, anti-slop engines, static UI + Deno gateway) is documented in `docs/06_PROGRESS.md`. The code audit in `docs/07_FLAGSHIP_REBUILD_AND_LAUNCH.md` §1 lists why it's being rebuilt: invented sources, fake confidence, gates that never gate.

---

## Phase status

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Feasibility spike | ✅ Done | `docs/spikes/phase0.md` — keyless discovery 80% (target 60%); models chosen |
| 1 | Repo & platform foundation | ✅ Done | uv workspace, Docker, compose, CI; 52 tests, ruff + mypy --strict clean |
| 1b | Next.js pixel-perfect port | ✅ Built (awaiting Supabase keys for live login) | `web/`, 0-px diff on 12 page×width combos |
| 2 | Database layer | ✅ Done | 27 tables, RLS, 2 migrations (up/down tested), 13 Postgres integration tests, backup + restore drill |
| 3 | Supabase Auth, tenancy | ✅ Done (live login pending keys; Turnstile pending Cloudflare keys) | JWT/JWKS verify, IDOR suites, rate limits, export/delete, nonce CSP |
| 4 | API v1, jobs, SSE | ✅ Done (crash-resume verified with the Phase 8 graph) | 14 v1 endpoints, taskiq worker, Valkey SSE, schemathesis contract suite |
| 5 | Keyless source layer | ✅ Done | `packages/sources`; 36 unit + 5 integration tests; live probe: every source healthy or blocked by policy |
| 6 | RAG | ✅ Done | `packages/rag`; live recall@10 1.0 / MRR 1.0 on 20-idea set; DB part 38 ms, end-to-end p95 2.6 s (NIM embed+rerank round-trips) |
| 7 | LLM layer | ✅ Done | `packages/llm`: router, shared NIM limiter, prompt registry, injection guard, usage/budget, cache, Langfuse hook |
| 8 | Validation graph (LangGraph) | ✅ Done (p95 over target) | 30-idea eval: junk refused 10/10, fabricated URLs 0, citation verified rate 0.84, verdict agreement 0.80, p95 373 s (target 240) |
| 9 | Content gates library | ✅ Done | L1–L4 + Delta voice + compliance; FPR 6% on 50 real pre-2022 posts, 100% catch on 50 default-AI posts |
| 10 | Trends, voice, content graph | ✅ Done | Voice (Delta), Story Bank, hook miner (live: 4+3 formulas measured), content graph with anti-fabrication gates |
| 11 | Frontend screens | 🟢 Core flow done | Workspace rewired to v1 with the same markup; verified in the browser: intake → live progress → verdict → plan → edit/re-gate → approve |
| 12 | Billing & quotas | 🟢 Built (needs Stripe keys) | Checkout, Portal, signed idempotent webhooks, usage vs quota |
| 13 | Observability & hardening | 🟢 Mostly | Prometheus, Sentry, runbooks (`docs/runbooks.md`), audits clean, load test 50 users p95 367 ms |
| 14 | Launch readiness, CI evals | ⬜ | — |

---

## Log

### 2026-09-24 — Phases 10–13 + end-to-end check (overnight session, continued)
- **Honesty rules** (the user's hard requirement: no fake numbers, no AI-sounding content):
  - Validation: claims cite only source ids they were shown; numbers must appear in the cited post; every citation is judged; signals and verdict are computed in Python.
  - Content: a draft may use numbers (digits or words) only from its Story Bank entry. Without an entry it may not narrate first-person experiences (`L1.unsourced_story`). The L5 editor check includes a fabrication tell (21). Hook labels are stripped.
  - UI: every LLM-invented figure (TAM/SAM/SOM, fixed stylometry stats, "84%" placeholders) is gone, replaced by measured signals, verified claims with links and real profile stats.
- **NIM quirks found live** (all fixed):
  - With `max_completion_tokens`, guided JSON runs to the limit; `max_tokens` is now sent via `extra_body`.
  - Guided JSON stalls with whitespace at true/false slots, so the citation judge and content judge use a strict line protocol (`P3 | SUPPORTED | 0.9`); a malformed line means unverified.
  - `json_schema` output with raw newlines is invalid, so drafts are plain text.
- **Phase 10:**
  - Voice samples plus a profile (function-word Burrows' Delta, calibrated threshold, blocking only with ≥5 samples of 80+ words).
  - Story Bank CRUD with the rule that numbers must be in the text; `/story-bank/extract` proposes entries.
  - Content graph (LangGraph `Send` per brief): deterministic schedule (community cadence, ≤1 promo in 10, never in no-promo communities) → draft → autofix → L1–L4 + voice + compliance → up to 2 targeted rewrites → L5 judge.
  - API: content plans (+SSE), drafts edit/re-gate/approve/export, `/gates/audit`, communities.
  - **Not yet done:** trend/hook miner (`hook_patterns` stays empty, so the planner says "none measured yet").
- **Phase 11:** `web/lib/api.ts` is a typed v1 client. All 6 workspace panes are rewired with identical class names and structure; the workspace restores the latest project, run and plan. Found and fixed in the browser:
  - Next's compression buffered SSE (`compress: false`; Caddy skips `text/event-stream`).
  - The API's Redis `socket_timeout=5` < the 15 s XREAD block (now 30).
  - Approve after edit targeted the old draft version.
  - Selection reset on refresh.
- **Phase 12:** `/api/v1/billing` (plan, status, usage vs quota), `/checkout`, `/portal`, `/webhook` (Stripe signature, `stripe_events` dedupe, subscription → `profiles.plan`, failed payment → past_due, cancel → Free). **Needs** `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`.
- **Phase 13:**
  - `deno_core.observability`: HTTP, run, node, source, LLM token/cost and gate metrics. `GET /metrics` needs a bearer `METRICS_TOKEN`, or loopback only; worker metrics on :9000.
  - Sentry (no PII) when `SENTRY_DSN` is set.
  - Deleted the v1 prototype: `deno_api/legacy/*` (invented TAM and sources), the old gate modules and their tests.
  - Dockerfile updated for the new packages. Image verified: 14 prompts ship, all modules import, production fails fast without secrets.
- **End-to-end in the browser** (API, worker, Next on `deno_dev`): new idea (freelancer invoice reminders) → live progress → verdict in 3 min 6 s (pivot 0.83, 56 posts, 15 supporting / 3 refuting verified claims) → 14-day plan (13/14 drafts gated) → edited a draft → live re-gate 0 issues → approved.
- **Later the same night:**
  - Hook miner: top 30 posts of the last 30 days per community (2 communities) → formula label per post (line protocol) → mean engagement ÷ community median, kept only if a formula has ≥2 posts → `hook_patterns` (24 h cache). The brief planner sees e.g. "F4 in r/Design (2.1x median)".
  - Without a Story Bank entry, hooks that need a real experience (F1, F2, F3, F6, F7, F11, F13, F15–F18) are swapped for opinion or question hooks.
  - The story gate also catches "I've talked to…" / "one of them told me…".
  - Live plan after these fixes: 4/7 drafts gated; the other 3 were **correctly blocked** for invented stories. Blocked drafts show the reason and can be edited.
  - Web: Past Validations list (switch projects); `/app/account` (plan, usage vs quota, upgrade/portal, JSON export, typed-DELETE account deletion); public `/legal/privacy`, `/legal/terms` and `/takedown` form.
  - **Validation eval** `evals/validation/` (10 good, 10 dead, 10 junk; results in `results.jsonl`):
    - junk → insufficient **10/10**; **0 fabricated URLs** across 30 runs; citation verified rate **0.836**; verdict agreement **0.80**; 0 failed runs; **p95 373 s** (target 240 s: misses).
    - Good ideas: 7 build, 3 insufficient (thin Reddit/X evidence).
    - Dead ideas: 5 insufficient, 1 kill, 2 pivot, **1 wrong build** (AI houseplant-mood app, confidence 0.46).
    - Fixed while running: Arctic Shift reports overload as HTTP 422 "slow down", so the Reddit source now retries it with backoff (before, some runs quietly lost all Reddit evidence). The eval script also retries transient NIM errors by resuming from the checkpoint, as the job queue does.
    - Open: SearXNG's Google/Brave/DDG engines CAPTCHA a single IP after ~30 runs (Bing still works); see `docs/runbooks.md`. p95 needs work (the citation judge dominates; more parallel batches or a smaller judge model).
  - Load test (`scripts/load_test.py`, 50 concurrent users, read endpoints, 2 uvicorn workers on a laptop): 2000 requests, 0 errors, 239 rps, p50 197 ms, p95 367 ms.
  - CI runs the gates eval and the offline retrieval eval. `pip-audit` (108 packages) and `npm audit` report 0 known vulnerabilities.
- **Local dev DB:** `deno_dev` (same container as tests; the test suite resets `deno_test`). CLI: `scripts/run_validation.py`, `scripts/run_content_plan.py`.
- **Tests:** 113 + 44 contract subtests; ruff, mypy --strict (79 files), tsc and eslint clean; `next build` OK.

### 2026-09-24 — Phases 6–9 (overnight autonomous session)
- **Phase 6 RAG** (`deno_rag`):
  - normalise (NFKC, boilerplate, English gate) → dedupe (content hash + canonical URL) → chunk (LangChain `RecursiveCharacterTextSplitter`, ~400/60 tokens; posts stay whole) → batch embed.
  - Hybrid retrieval: pgvector HNSW (iterative scan) + FTS → RRF → NIM rerank. `retrieve_many` does one embed call for several queries.
  - Tenant filtering lives in `UserScope`.
  - Eval: `evals/retrieval/` (20 ideas × 8 synthetic posts, generated once by Nemotron, labelled `synthetic`). Live results: recall@10 1.0, MRR 1.0, nDCG 0.99. Offline baseline 0.64. p95 is 2.6 s end to end; the DB part takes 38 ms (target 300 ms is only reachable with a local embedder).
- **Phase 7 LLM** (`deno_llm`):
  - `LLMRouter` uses `init_chat_model(provider="openai", base_url=NIM)` because ChatNVIDIA's `guided_json` is now rejected by NIM (400). Structured output uses `json_schema`, with `json_mode` on the fallback model.
  - Nemotron "thinking" is off by default (`LLM_THINKING_ROLES`): 0.8 s vs 7.7 s, and it caused length overruns.
  - One NIM budget (`ValkeyLimiter`, 36/min) covers chat, embeddings and rerank.
  - Versioned YAML prompts; id/version logged per call.
  - `<untrusted_source>` wrapping plus `assert_grounded`.
  - `UsageTracker` (tokens/cost per model, hard budget stop), exact `StructuredCache`, Langfuse callback when keys are set.
- **Phase 8 graph** (`deno_graphs.validation`):
  - Flow: intake → perspectives → query plan → `Send` collect per source → ingest → coverage gate → `Send` 7 analysts → citation judge → deterministic signals → critic ⇄ refiner → rule verdict + grounded rationale → account → review `interrupt` → finalize.
  - Checkpointed with `AsyncPostgresSaver` (verified: a failed run resumed from its checkpoint and finished).
  - **Anti-fabrication:**
    - Claims may cite only the source ids they were shown.
    - Any number in a claim must appear verbatim in a cited source, otherwise the claim is dropped.
    - Every citation is judged for entailment; unverifiable means dropped.
    - Signals and the verdict band are pure Python.
    - The rationale is rejected (deterministic fallback used) if it has numbers not in signals/claims, unknown claim refs or slop words.
  - Worker registers it automatically. CLI: `scripts/run_validation.py "idea" [--no-review] [--resume RUN_ID]`.
  - Live result (churn-prediction idea): 89 posts (Reddit, HN, X, PH), 21 verified claims, verdict **pivot 0.65**, "5 verified pain claims, but demand or payment evidence is thin or contested; crowded: 12 competitor mentions".
  - Source fixes found live: Arctic Shift times out on multi-word full-text in big subs, so the API gets the longest word and the others are matched locally. 4xx no longer trips the circuit breaker.
- **Phase 9 gates** (`deno_gates`, new layered API; the v1 modules remain only for the legacy UI):
  - Layers:
    - L1 scrub/autofix: leakage, placeholders, markdown on LinkedIn, em dashes, unsourced numbers vs the Story Bank.
    - L2: 20 pattern rules; every match is reported with its span.
    - L3: per-paragraph density.
    - L4: triads, contrasts, fragments, monotone rhythm, broetry.
  - Voice uses function-word Burrows' Delta with a threshold calibrated between the author's spread and other writers. It blocks only with a strong profile (≥5 samples averaging 80+ words).
  - Compliance comes from community rules; the fake `ai_detection_probability` is gone.
  - Golden corpus `evals/gates/`: 50 real Reddit posts from before 2022-06 plus 50 default Nemotron posts. **FPR 6%, catch 100%**; a pytest guards both thresholds.
- **Tests:** 142 + 21 contract subtests pass; ruff and mypy --strict clean on 85 files.

### 2026-09-24 — Phase 5 (done)
- **Fixed:** X oEmbed dates were naive and crashed the `since` comparison. `Post` now forces `published_at`/`fetched_at` to aware UTC (naive → UTC). Covered by a regression test.
- **SearXNG:** Brave rate-limits and DuckDuckGo CAPTCHAs from a single IP. Google and Bing ship disabled; `deploy/searxng/settings.yml` now enables them. Product Hunt and X discovery recovered.
- **Live probe** (`scripts/probe_sources.py`, exit 0): Reddit 20 (arctic_shift), X 5 (oembed), HN 10, Product Hunt 10. LinkedIn posts/jobs are `blocked_by_policy` (robots.txt, no opt-in). Trends is empty for this query (context only).
- **Settings:** `SOURCES_ROBOTS_OPT_IN` (comma-separated hosts, default empty = obey robots.txt) and `SOURCES_USER_AGENT`.
- **Per-source daily caps** (`registry.DAILY_CAPS`, counted in the shared cache; cache hits are free) → `SourceUnavailable` when reached.
- **source_health:** `Fetcher.drain_health()` returns deltas; `repositories.record_source_health()` upserts hourly buckets (counters add up, p95 keeps the worst); `source_health_summary()` feeds alerts. The graph runtime flushes after each run (Phase 8).
- **Takedowns:** `POST /api/v1/takedowns` is public, rate-limited to 5/h per IP and **only records** the request, so nobody can erase other users' evidence. An admin (`profiles.role='admin'`, set in SQL; profiles are read-only under RLS) can call `GET /api/v1/admin/takedowns` and `POST …/{id}/approve|reject`. Approve purges matching text across all tenants. Non-admins get a 404.
- **CI:** `.github/workflows/source-probe.yml` runs nightly and is non-blocking.
- **Tests:** 128 + 21 contract subtests pass; ruff and mypy --strict clean.

### 2026-09-24 — Phase 5 (in progress)
- **Done:** `packages/sources` (`deno_sources`) contains:
  - `net.Fetcher`: allow-list, SSRF guard, robots.txt enforcement with operator opt-in, circuit breaker, cache, per-host token bucket, retries honouring Retry-After / X-RateLimit-Reset, health stats.
  - Clients: Reddit (Arctic Shift), HN (Algolia), X (SearXNG discovery → syndication if opted in, else oEmbed via publish.x.com), LinkedIn posts (JSON-LD) and jobs (guest API), Product Hunt (Atom + search), Google Trends RSS, plus `registry.py`.
  - Anonymised fixtures in `tests/fixtures/sources/`; 32 unit tests. Full suite 114 + 17 contract subtests, lint and types clean.
- **Compliance finding (needs your decision):** robots.txt disallows bots on LinkedIn (its ToS also bans automated access), reddit.com and cdn.syndication.twimg.com. These are **off by default** and need an explicit `robots_opt_in`. Arctic Shift, HN Algolia, X oEmbed, Product Hunt feed and Google Trends are allowed. Legal review is recommended before production.
- **Next steps:**
  1. Fix the bug the live probe found: oEmbed dates are naive, so the `since` comparison crashes. Normalise `Post.published_at` to UTC in a model validator.
  2. Re-run `uv run python scripts/probe_sources.py` (optionally `--opt-in www.linkedin.com,cdn.syndication.twimg.com`).
  3. Add `SOURCES_ROBOTS_OPT_IN` to settings.
  4. Persist `source_health` to the table.
  5. Add a takedown endpoint.
  6. Continue with Phase 6 (RAG).

### 2026-09-24 — Phases 3 + 4
- **API v1** (`/api/v1`, OpenAPI at `/api/v1/openapi.json`):
  - Endpoints: projects CRUD with cursor pagination; `POST /projects/{id}/runs` → 202 with an `Idempotency-Key`; runs get/cancel/resume; `GET /runs/{id}/events` (SSE); report, evidence explorer and claim detail; `/me`, `/me/export`, `DELETE /me` (data plus Supabase login via the admin API).
  - Every route goes through `UserScope`, so a foreign id is a 404.
  - Per-user sliding-window rate limit (Valkey, 60/min, fails open), per-plan concurrency and monthly quotas (402/429), 1 MiB body limit, and documented error envelopes.
- **Jobs:** taskiq on Valkey Streams (ADR-004 changed from arq, which pins redis<6).
  - Delivery is acknowledged; unacknowledged jobs are re-claimed after 15 min.
  - A self-renewing Valkey lease guarantees one execution per run.
  - Retries (exponential with jitter) only for transient errors.
  - Runs enqueue after commit, with a once-a-minute cron that re-queues runs stuck in `queued`.
  - The nightly retention purge is scheduled.
  - The worker/scheduler share the backend image; compose has `worker`, `scheduler` and a `migrate` profile.
- **Run lifecycle** (`deno_core.runs`): queued → running → succeeded/failed/cancelled/awaiting_review, with cooperative cancellation and events on a Valkey stream. SSE supports `Last-Event-ID` resume and 15 s heartbeats, and the stream holds no DB connection. The in-memory progress dict now serves only the legacy `/api/*` routes, which the UI still uses until Phase 11.
- **Verified end to end** with real processes: HTTP → Postgres → taskiq → worker → SSE (the run failed with `runner_not_configured` because no graph is deployed yet).
- **Contract tests** (schemathesis, 8/8 stable) found and fixed three bugs:
  - 405s were missing the full `Allow` header.
  - NUL bytes and lone surrogates crashed Postgres inserts (fixed by `CleanText` on all text inputs).
  - The schema accepted whitespace-only ideas that the domain rejected.
- **Web CSP:** per-request script nonce + `strict-dynamic`; inline styles allowed (pixel-parity markup); Google Fonts and Supabase allow-listed. 0 browser violations, pixel diff still 0 px.
- **Tests:** 82 + 17 contract subtests. ruff and mypy --strict clean on 37 files.

### 2026-09-24 — Phase 2
- **Schema** (`deno_core.db.models`): 27 tables covering identity (`profiles`), projects/runs, evidence (`source_documents`, `chunks` with `halfvec(2048)` HNSW + generated `tsvector` GIN), findings (claims/citations/signals/verdicts with a DB-level 0–1 confidence check), communities (global), voice, content, billing and ops. Keys are UUIDv7 and every tenant table has an indexed `user_id`.
- **Repositories** (`deno_core.db.repositories.UserScope`): all tenant access is filtered by `user_id` in one place, and a foreign id raises `NotFound` exactly like a missing one. Also covers cursor pagination, run idempotency keys, per-run document dedupe, the usage ledger, GDPR export/delete, the 90-day scraped-text purge (keeps URL, hash and citations) and cross-tenant takedown purge.
- **Migrations** (Alembic, async):
  - `0001` creates the schema plus RLS on every table: `owner_all` policies for `authenticated`, public-read for reference tables, deny-all for ops tables. A Supabase-compat prelude (roles, `auth.uid()`, pgvector) is a no-op on Supabase and makes plain Postgres behave the same.
  - A `private.handle_new_user()` trigger creates profiles on sign-up (Supabase only).
  - `0002` seeds 12 communities and rules from docs/05 (`verified_at` NULL until checked live) and placeholder quotas.
  - Up → down → up and `alembic check` are clean.
- **Tests:** 13 integration tests on Postgres 17 + pgvector 0.8. They cover cross-tenant isolation, forced ownership, RLS through the `authenticated` role, vector and full-text search, purge/takedown, export/delete, idempotency and pagination. They run in a throwaway container locally and as a service container in CI, and are skipped if unreachable.
- **Backups:** `deploy/backup/backup.sh` (`pg_dump` → restic or local, 30d/12m retention) and `restore_drill.sh` (restores into a scratch DB, verifies, fails loudly — a truncated dump exits 1).
- **Deferred to their phases:** nightly purge scheduling (worker, Phase 4); LangGraph `PostgresSaver.setup()` (Phase 8).

### 2026-09-24 — Phase 1
- **uv workspace:** `packages/gates` (`deno_gates`, the future open-source `deno-slop-gate`), `packages/core` (`deno_core`: settings, logging, errors, schemas), `apps/api` (`deno_api`). v1 pipelines kept reachable under `deno_api/legacy/` until Phases 8/10 replace them. `backend/` removed; history preserved with `git mv`.
- **Platform:**
  - `pydantic-settings` config with secret files; production fails fast without Supabase, NIM key and a Postgres URL.
  - structlog JSON logs with a request id on every line and response.
  - One error envelope `{error:{code,message,request_id}}`. Stack traces and exception text never reach clients (fixes the SSE message leaking `str(exc)`).
  - `/healthz` + `/readyz` with pluggable checks.
- **Tests:** moved to `tests/unit|live`, on a temp SQLite (no longer writing the real DB). Live tests are auto-marked and excluded by default.
- **Containers:** `Dockerfile` (one backend image for API/worker/scheduler/migrate; uv, multi-stage, non-root uid 10001, healthcheck) and `web/Dockerfile` (Next standalone). `compose.dev.yml` (api, web, valkey, searxng) runs the whole stack. `compose.prod.yml` adds Caddy with automatic TLS.
- **CI** (`.github/workflows/ci.yml`): ruff → mypy → pytest with Postgres+pgvector and Valkey service containers → web lint/types/build → image builds + Trivy → gitleaks. Also Dependabot and pre-commit.

### 2026-09-24 — Phases 0, 1b, 3 (part)
- **Plan revised:** Supabase Auth replaces in-house auth (ADR-003); Next.js replaces the vanilla UI + Deno gateway (ADR-010, new Phase 1b); Postgres hosted by Supabase (ADR-001).
- **Phase 1b:** `web/` Next.js 16 app. The v1 CSS files are reused byte-for-byte, and each page has its own root layout so styles never leak. `npm run test:visual` diffs every page at 1440/1024/390 px against `public/` → **0 px**. Interactive states match too.
- **Phase 3 (part):** login, sign-up, Google OAuth, password reset, sign-out and protected `/app` via `@supabase/ssr`. FastAPI verifies Supabase JWTs against the JWKS (algorithm pinned by the JWK, HS256 only with an explicit legacy secret) and scopes projects by owner (404 on foreign ids). CORS is an allow-list, and production refuses to start without `SUPABASE_URL`. 45 backend tests pass.
- **Phase 0:** see `docs/spikes/phase0.md`.
  - LLM: `nvidia/nemotron-3-super-120b-a12b` (~1.2 s to first token, structured output works); fallback `meta/llama-3.2-11b-vision-instruct`. Many listed NIM models return 404 or time out in the queue.
  - RAG: embeddings `nvidia/nemotron-3-embed-1b` (2048-d → `halfvec`); rerank `nvidia/llama-nemotron-rerank-vl-1b-v2`.
  - Discovery: SearXNG + X syndication + LinkedIn public pages. 8/10 ideas get ≥10 hydrated posts, X 98% / LinkedIn 100% hydration, no authwalls.

---

## How to run (current)

```bash
# Local services (Postgres+pgvector, Valkey, SearXNG)
docker compose -f compose.dev.yml --profile test up -d postgres-test valkey searxng
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/deno_dev
uv run alembic -x url=$DATABASE_URL upgrade head        # once
# API (:8000), worker (runs the graphs), web (:3000)
uv run uvicorn deno_api.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker deno_worker.tasks:broker --workers 1
cd web && npm run dev      # web/.env.local: Supabase URL + publishable key (empty = dev auth)
# Tests
uv run pytest              # unit + integration (resets deno_test); live: uv run pytest -m live
cd web && npm run lint && npx tsc --noEmit && npm run build
# Evals
uv run python evals/retrieval/run_eval.py [--live]
uv run python evals/gates/run_eval.py
```

## Deploy (one VPS, docs/08 ADR-011)

```bash
docker build -t $REGISTRY/api:$TAG . && docker build -t $REGISTRY/web:$TAG web/
cp .env.example .env.production   # fill in secrets
DOMAIN=deno.example.com SEARXNG_SECRET=$(openssl rand -hex 16) \
  docker compose -f compose.prod.yml --profile migrate run --rm migrate
DOMAIN=deno.example.com SEARXNG_SECRET=... docker compose -f compose.prod.yml up -d
```
Web build needs `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` at build time and `BACKEND_URL=http://api:8000` at runtime. Stripe webhook URL: `https://$DOMAIN/api/v1/billing/webhook`.

## Waiting on (you)

- Supabase project URL + publishable key (live login test; then `public/` and `gateway/` are deleted).
- Stripe keys + a Pro price id (billing); pricing decision for quotas (placeholders: Free 5 runs/1 plan, Pro 50/20).
- Legal review before opting in to LinkedIn / Reddit / X syndication (`SOURCES_ROBOTS_OPT_IN`).
- Optional: `SENTRY_DSN`, `LANGFUSE_*`, `METRICS_TOKEN`.
