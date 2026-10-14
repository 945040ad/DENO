# Deno — Configuration Reference

Every variable the backend and the web app read: what it does, its default, and what production uses
today. Deployment steps are in [`09_FREE_DEPLOYMENT.md`](09_FREE_DEPLOYMENT.md).

## 1. Where values live

| Place | Read by | Committed? |
|---|---|---|
| `.env` (repo root) | API, worker, scheduler, Alembic, scripts, when run locally | **No** (gitignored) |
| `.env.example` | template for `.env` | yes |
| `web/.env.local` | Next.js dev server and builds on your machine; `vercel link` also adds `VERCEL_OIDC_TOKEN` | **No** |
| `web/.env.example` | template for `web/.env.local` | yes |
| Cloud Run `deno-api` / `deno-run` env vars | production backend (plain values) | set by `deploy/deploy-free.sh` |
| Google Secret Manager | production backend secrets, mounted as env vars | never in git |
| Vercel project env (Production) | production web build and runtime | set by `deploy/deploy-free.sh` |
| `.env.production` | VPS deploy with `compose.prod.yml` only | **No** |

How the backend loads settings (`packages/core/src/deno_core/settings.py`, pydantic-settings), highest
priority first:
1. Environment variables.
2. Secret files in `DENO_SECRETS_DIR`, one file per setting name (Docker / Kubernetes secrets).
3. The env file `DENO_ENV_FILE` (default `.env` in the working directory).

Names are case-insensitive, and unknown variables are ignored (so `NVIDIA_NIM_MODEL`, `GATEWAY_PORT`
and other leftovers in an old `.env` do nothing). Lists are comma-separated.

With `ENVIRONMENT=production` the process **refuses to start** unless `SUPABASE_URL`,
`NVIDIA_NIM_API_KEY` and a `postgresql…` `DATABASE_URL` are set, and, with `TASK_RUNNER=cloudrun_job`,
a full `CLOUDRUN_JOB` name.

Legend for the **Prod** column: 🔒 = from Secret Manager, `—` = not set (default applies).

---

## 2. Backend variables

### Core
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `ENVIRONMENT` | `development` | `production` | `development` / `test` / `staging` / `production`. Production turns on the startup checks above |
| `LOG_LEVEL` | `info` | — | `debug` / `info` / `warning` / `error` |
| `LOG_JSON` | `true` | `true` | structlog JSON lines (Cloud Logging parses them). `false` = readable dev output |

### LLM (NVIDIA NIM)
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `NVIDIA_NIM_API_KEY` | — | 🔒 `nim-key` | One key for every LLM, embedding and rerank call (40 req/min hard cap) |
| `NVIDIA_NIM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | same | OpenAI-compatible endpoint |
| `LLM_MODEL_FAST` | `nvidia/nemotron-3-super-120b-a12b` | — | `Role.FAST`: short structured calls (max 1500 tokens, ½ timeout) |
| `LLM_MODEL_STRONG` | same | — | `Role.STRONG`: long reasoning (max 3000 tokens, 1.5× timeout) |
| `LLM_MODEL_JUDGE` | same | — | `Role.JUDGE`: grading (max 1200 tokens) |
| `LLM_MODEL_FALLBACK` | `meta/llama-3.2-11b-vision-instruct` | — | Every role falls back to it on error (`deno_llm/router.py`) |
| `LLM_PROVIDER` | `openai` | — | LangChain `init_chat_model` provider; `openai` = NIM's OpenAI-compatible API |
| `LLM_STRUCTURED_METHOD` | `json_schema` | — | `json_schema` / `json_mode` / `function_calling` (function calling doesn't work on NIM) |
| `LLM_REQUESTS_PER_MINUTE` | `36` | — | Client-side limiter, 1–40, shared through Redis |
| `LLM_TIMEOUT_SECONDS` | `60` | — | Per call |
| `LLM_THINKING_ROLES` | empty | — | Roles that keep Nemotron "thinking" on (about 10× slower), e.g. `judge` |
| `LLM_RUN_TOKEN_BUDGET` | `400000` | — | Hard stop per validation run |
| `LLM_USD_PER_MTOK_INPUT` / `_OUTPUT` | `0` | — | Cost accounting; NIM trial keys are free |
| `EMBED_MODEL` | `nvidia/nemotron-3-embed-1b` | — | 2048-d embeddings (stored as `halfvec`) |
| `RERANK_MODEL` | `nvidia/llama-nemotron-rerank-vl-1b-v2` | — | Reranker for retrieval |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | empty | — | LLM tracing (optional) |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | — | |

### Data
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `DATABASE_URL` | empty | 🔒 `database-url` | `postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres` (session pooler, IPv4). Also used by Alembic |
| `VALKEY_URL` | `redis://127.0.0.1:6379/0` | 🔒 `valkey-url` | Redis/Valkey: run events (SSE), run leases, rate limits, LLM cache, taskiq broker. `rediss://` for Upstash |
| `SCRAPED_TEXT_RETENTION_DAYS` | `90` | — | The purge cron deletes scraped text older than this |
| `TEST_DATABASE_URL` | local `postgres-test` | n/a | Integration tests only. Never point it at Supabase: the tests drop every table, and the test setup refuses Supabase hosts |

### Auth (Supabase)
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `SUPABASE_URL` | empty | `https://bfinvyflanpjfzlisspq.supabase.co` | JWKS for token checks. Empty = dev mode (every request is one fixed dev user) |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | — | Expected `aud` claim |
| `SUPABASE_LEGACY_JWT_SECRET` | empty | — | Only for old projects on shared HS256 secrets |
| `SUPABASE_SECRET_KEY` | empty | 🔒 `supabase-secret` | `sb_secret_…`, server only. `DELETE /me` uses it to remove the login too |

### Search and sources
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `SEARXNG_URL` | `http://127.0.0.1:8890` | `https://deno-searxng-86239723863.asia-northeast1.run.app` | Metasearch for discovery |
| `SEARXNG_GCP_AUTH` | `false` | `true` | Attach a Google ID token (SearXNG is a private Cloud Run service) |
| `SOURCES_ROBOTS_OPT_IN` | empty | — | Hosts fetched even though robots.txt disallows bots. **Only after legal review** |
| `SOURCES_USER_AGENT` | empty | — | Custom fetcher user agent |
| `GITHUB_TOKEN` | empty | — | Optional. Ideas that link a public GitHub repo are read through api.github.com (description, topics, README). Without a token GitHub allows 60 requests/hour per IP (2 per run); a fine-grained token with no scopes raises that to 5,000 |
| `TAKEDOWN_RATE_LIMIT_PER_HOUR` | `5` | — | Public takedown form limit |

### Jobs and crons
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `TASK_RUNNER` | `taskiq` | `cloudrun_job` | `taskiq` = Valkey queue + worker (compose/VPS); `cloudrun_job` = one Cloud Run Job execution per run |
| `CLOUDRUN_JOB` | empty | `projects/deno-gtm/locations/asia-northeast1/jobs/deno-run` | Full job name |
| `CRON_OIDC_AUDIENCE` | empty | the API URL | Expected `aud` of Cloud Scheduler's token |
| `CRON_SERVICE_ACCOUNT` | empty | `deno-scheduler@deno-gtm.iam.gserviceaccount.com` | Expected caller. Both cron settings empty = `/internal/cron/*` answers 404 |

### Billing (Stripe, not live yet)
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | empty | — | Billing endpoints answer 503 until this and the price are set |
| `STRIPE_WEBHOOK_SECRET` | empty | — | Verifies `/api/v1/billing/webhook` |
| `STRIPE_PRICE_PRO` | empty | — | `price_…` for Pro monthly |
| `APP_URL` | `http://localhost:3000` | `https://deno-web-eight.vercel.app` | Where Stripe sends people back |

### Observability
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `SENTRY_DSN` | empty | — | Error reporting |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.05` | — | 0–1 |
| `METRICS_TOKEN` | empty | — | Bearer token for `GET /metrics`; empty = loopback only |
| `WORKER_METRICS_PORT` | `9000` | — | taskiq worker Prometheus port |

### HTTP
| Variable | Default | Prod | Purpose |
|---|---|---|---|
| `WEB_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | `https://deno-web-eight.vercel.app` | CORS allow-list for browsers calling the API directly |
| `BACKEND_HOST` / `BACKEND_PORT` | `127.0.0.1` / `8000` | — | Local uvicorn bind (the image always listens on `0.0.0.0:8000`) |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | — | Per-user API limit |
| `REQUEST_MAX_BYTES` | `1048576` | — | Request body cap |

### Process-level
| Variable | Purpose |
|---|---|
| `DENO_ENV_FILE` | Env file path (default `.env`) |
| `DENO_SECRETS_DIR` | Directory of secret files |

---

## 3. Web variables (`web/`)

| Variable | Exposed to browser | Prod (Vercel) | Purpose |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | yes | `https://bfinvyflanpjfzlisspq.supabase.co` | Supabase client |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | yes | `sb_publishable_…` | Browser-safe key. **Never** put the secret key in `web/` |
| `NEXT_PUBLIC_SITE_URL` | yes | `https://deno-web-eight.vercel.app` | Auth email and OAuth redirects |
| `BACKEND_URL` | no (Vercel "Secret" type) | `https://deno-api-46vgcwltwa-an.a.run.app` | Target of the `/api/*` rewrite in `next.config.ts` |

All four are read **at build time**: after changing one, redeploy. With both Supabase variables empty,
the web app runs in dev mode (no login needed).

---

## 4. Production secrets (Google Secret Manager, project `deno-gtm`)

| Secret | Env var | Rotate with |
|---|---|---|
| `database-url` | `DATABASE_URL` | `gcloud secrets versions add database-url --data-file=-`, then a new API revision (docs/09 §8) |
| `nim-key` | `NVIDIA_NIM_API_KEY` | same |
| `valkey-url` | `VALKEY_URL` | same |
| `supabase-secret` | `SUPABASE_SECRET_KEY` | same |

Only `deno-api@deno-gtm.iam.gserviceaccount.com` can read them.

---

## 5. Deploy-time constants (`deploy/deploy-free.sh`)

| Constant | Value |
|---|---|
| `P` (project) | `deno-gtm` |
| `R` (region) | `asia-northeast1` |
| `IMAGE` | `asia-northeast1-docker.pkg.dev/deno-gtm/deno/api:<git short sha>` |
| `API_SA` / `SCHED_SA` | `deno-api@…` / `deno-scheduler@…` |
| `SEARXNG_URL` | the private SearXNG service URL |
| `VERCEL_PROJECT` | `deno-web` (overridable from the environment) |
| `GCLOUD` | gcloud binary (default `~/google-cloud-sdk/bin/gcloud`) |
