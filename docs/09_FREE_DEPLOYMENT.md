# Deno — Deployment Guide (free tier, no VPS)

**Status: live since 2026-10-13.**

| | |
|---|---|
| Web (public) | https://deno-web-eight.vercel.app |
| API | https://deno-api-46vgcwltwa-an.a.run.app (also `https://deno-api-86239723863.asia-northeast1.run.app`) |
| Readiness | `GET <API>/readyz` → `{"status":"ok","checks":{"database":"ok","valkey":"ok"}}` |
| Google Cloud project | `deno-gtm` (number `86239723863`), region `asia-northeast1` (Tokyo) |
| Vercel | team `chaharatul92-7596s-projects`, project `deno-web`, Root Directory `web` |
| Supabase | project `bfinvyflanpjfzlisspq`, region `ap-northeast-1` (Tokyo) |
| Redis | Upstash, `ap-northeast-1` |

The whole product runs for $0/month on free tiers, with no server to manage, and the Python backend
(FastAPI, LangGraph, NumPy) runs unchanged. Every variable is described in
[`10_CONFIGURATION.md`](10_CONFIGURATION.md); the tech stack is in [`11_TECH_STACK.md`](11_TECH_STACK.md).
The older single-VPS path (`compose.prod.yml`, docs/08 ADR-011) still works and is the move once steady
traffic makes free quotas awkward (§10).

---

## 1. Architecture

```
                         ┌──────────────── Vercel (Hobby) ────────────────┐
browser ──HTTPS──────────► Next.js 16 (web/)                              │
   │                     │   pages, Supabase session cookies (@supabase/ssr)
   │                     │   /api/*  ── rewrite ──┐                       │
   │                     └────────────────────────┼───────────────────────┘
   │                                              ▼
   │                     ┌──────── Google Cloud Run, asia-northeast1 ─────┐
   │                     │ service deno-api  (FastAPI, uvicorn :8000)     │
   │                     │   │ enqueue run ─► Cloud Run Admin API         │
   │                     │   │                 └► job deno-run (1 execution per run,
   │                     │   │                     python -m deno_worker.run_once)
   │                     │   └► service deno-searxng (private, ID-token auth)
   │                     └──────▲─────────────────────────────────────────┘
   │                            │ OIDC  POST /internal/cron/{purge,requeue}
   │                     Cloud Scheduler (deno-purge daily, deno-requeue every 5 min)
   │
   └── Supabase Auth (login, OAuth, email links)
       deno-api / deno-run ──► Supabase Postgres + pgvector (session pooler :5432)
                          ──► Upstash Redis (rediss://: run events for SSE, leases, rate limits)
                          ──► NVIDIA NIM (LLM, embeddings, rerank; 40 req/min per key)
```

How one validation run flows:

1. The browser calls `POST /api/v1/projects/{id}/runs` on the Vercel origin. Next.js rewrites it to the API.
2. The API checks the Supabase JWT, writes the run row, then calls `deno_core.jobs.enqueue`. With
   `TASK_RUNNER=cloudrun_job` that starts one execution of the `deno-run` job with the arguments
   `-m deno_worker.run_once validation.run '{"run_id": …, "user_id": …}'`.
3. The job runs the LangGraph validation graph, checkpointing to Postgres and publishing progress events
   to Redis.
4. The browser listens on the run's SSE endpoint. The API reads the Redis events and streams them out.
5. Exit codes: `0` = run finished (including runs that end `failed`), `1` = transient error (Cloud Run
   retries up to 2 times and the graph resumes from its checkpoint), `2` = bad invocation.

`deno-requeue` (every 5 min) re-sends runs whose enqueue was lost. `deno-purge` (03:17 daily) deletes
scraped text past `SCRAPED_TEXT_RETENTION_DAYS`, and also counts as activity, so the free Supabase
project doesn't pause.

---

## 2. What runs where

| Piece | Where | Name | Notes |
|---|---|---|---|
| Next.js web | Vercel Hobby | `deno-web` | Builds from GitHub `main`, Root Directory `web` |
| FastAPI API | Cloud Run service | `deno-api` | Public; 0–2 instances, 1 GiB, 3600 s timeout |
| Graph runs | Cloud Run job | `deno-run` | Same image as the API, 30 min task timeout, 2 retries |
| Web search | Cloud Run service | `deno-searxng` | Private; only `deno-api@` may invoke it |
| Crons | Cloud Scheduler | `deno-purge`, `deno-requeue` | OIDC as `deno-scheduler@` |
| Images | Artifact Registry | `asia-northeast1-docker.pkg.dev/deno-gtm/deno/{api,searxng}:<git sha>` | Built by Cloud Build |
| Secrets | Secret Manager | `database-url`, `nim-key`, `valkey-url`, `supabase-secret` | Mounted as env vars |
| Postgres + Auth | Supabase Free | `bfinvyflanpjfzlisspq` | Migrations via Alembic |
| Redis | Upstash Free | — | TLS `rediss://` |
| LLM | NVIDIA NIM | — | Free trial key |

Service accounts:

| Account | Used by | Roles |
|---|---|---|
| `deno-api@deno-gtm.iam.gserviceaccount.com` | `deno-api`, `deno-run` | `secretmanager.secretAccessor`, `run.developer` (project); `iam.serviceAccountUser` on itself; `run.invoker` on `deno-searxng` |
| `deno-scheduler@deno-gtm.iam.gserviceaccount.com` | Cloud Scheduler | none (the API checks its OIDC token itself) |

---

## 3. Free-tier limits

Re-check each provider's pricing page now and then; quotas change.

- **NVIDIA NIM:** 40 requests/min per key, shared by every user. This is the first real limit, not hosting.
- **Supabase Free:** pauses after 7 days without activity; database size cap of about 500 MB; 2 free projects.
  The built-in email sender allows only a few emails an hour (set up custom SMTP, §9).
- **Cloud Run:** monthly free allowance of requests, vCPU-seconds and GiB-seconds; scales to zero, so the
  first request after idle has a cold start of a few seconds. A billing account is required.
  **Budget:** ₹100 alert on billing account `01E882-729D93-38BF9F` (the account is in INR, so a `USD`
  budget is rejected).
- **Cloud Scheduler:** 3 free jobs per billing account (we use 2).
- **Artifact Registry:** 0.5 GB free storage. Delete old image tags now and then (§8).
- **Vercel Hobby:** non-commercial use only. Once you charge money, use Vercel Pro or move the web app
  (Cloudflare Pages via `@opennextjs/cloudflare`, or Netlify).
- **Upstash Free:** capped commands per month. That's why there is no always-polling taskiq worker in
  this deployment.

---

## 4. Tools you need on your machine

| Tool | Install | Login |
|---|---|---|
| Google Cloud CLI | `curl -sSLO https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz && tar -xzf google-cloud-cli-linux-x86_64.tar.gz -C ~ && ~/google-cloud-sdk/install.sh` | `gcloud auth login` and `gcloud config set project deno-gtm` |
| Vercel CLI | `npm i -g vercel` | `vercel login` |
| uv (Python) | https://docs.astral.sh/uv/ | — |
| Node 20+ / npm | — | — |
| GitHub CLI (optional) | — | `gh auth login` |

`gcloud` lives at `~/google-cloud-sdk/bin/gcloud`. The deploy script uses that path unless `GCLOUD` is set.

---

## 5. Releasing an update (the usual case)

### Web only (`web/` changed)
Push to `main`. Vercel builds `web/` and promotes it to production automatically. Watch it with
`vercel ls deno-web`, or in the Vercel dashboard.

### Backend (`apps/`, `packages/`, `migrations/` changed)
```bash
git push origin main                        # the image tag is the current commit's short sha
uv run alembic upgrade head                 # only if there is a new migration (DATABASE_URL in .env = prod DB)
bash deploy/deploy-free.sh                  # builds the image, updates job + API + scheduler + web
```
The script is idempotent: it builds the image only when the tag is missing, creates or updates
each resource, and prints the web and API URLs at the end. To deploy just the backend by hand:

```bash
G=~/google-cloud-sdk/bin/gcloud; R=asia-northeast1
IMAGE=$R-docker.pkg.dev/deno-gtm/deno/api:$(git rev-parse --short HEAD)
$G builds submit . --region $R --config deploy/cloudbuild-api.yaml --substitutions _IMAGE=$IMAGE
$G run jobs update deno-run --image $IMAGE --region $R
$G run deploy deno-api --image $IMAGE --region $R
```
Always update **both** `deno-run` and `deno-api` to the same image, or runs execute old graph code.

Run migrations **before** deploying code that needs them, and only add backward-compatible
migrations. During the rollout, the old revision keeps serving.

---

## 6. Deploying from scratch (new project or new environment)

Follow this order. Replace `deno-gtm`, the region and the URLs if you build a second environment.

### 6.1 Supabase
1. Create a project in the region nearest your Cloud Run region (we use Tokyo for both).
2. Set up Auth exactly as in [`supabase-setup.md`](supabase-setup.md): email confirmation, Google
   provider, TOTP, and **URL Configuration** with Site URL = the web URL and Redirect URLs =
   `<web URL>/**` (plus `http://localhost:3000/**` for development).
3. **Connect → Session pooler** (port 5432, IPv4). Change the scheme to `postgresql+asyncpg://` and put it
   into `.env` as `DATABASE_URL`. Don't use the direct `db.<ref>.supabase.co` host: it is IPv6-only and Cloud
   Run egress is IPv4. New projects may use an `aws-1-…` pooler host; copy it exactly.
4. Create the tables: `uv run alembic upgrade head` (check with `uv run alembic current` → `0003 (head)`).
5. Copy the `sb_secret_…` key to `.env` as `SUPABASE_SECRET_KEY`, and the URL and publishable key into
   `web/.env.local`.

### 6.2 Upstash
Create a Redis database (Free, same region), and copy the `rediss://default:…@….upstash.io:6379` URL into
`.env` as `VALKEY_URL`. Check it: `uv run python -c "import redis;print(redis.from_url('$URL').ping())"`.

### 6.3 Google Cloud project and billing
1. https://console.cloud.google.com/billing → create a billing account (card required; the bill stays $0
   on free usage). If an account shows `OPEN False`, its setup wasn't finished; create a new one.
2. Create the project, then link billing:
   `gcloud billing projects link deno-gtm --billing-account <ACCOUNT_ID>`
   (`gcloud billing accounts list` shows the IDs; only accounts with `OPEN True` work).
3. Budget alert, in your billing currency:
   ```bash
   gcloud billing budgets create --billing-account <ACCOUNT_ID> --display-name deno-budget \
     --budget-amount 100INR --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
   ```
   Find the currency with `gcloud billing accounts describe <ACCOUNT_ID> --format='value(currencyCode)'`.

### 6.4 APIs, registry, service accounts, IAM
```bash
P=deno-gtm; R=asia-northeast1
gcloud config set project $P
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com billingbudgets.googleapis.com
gcloud artifacts repositories create deno --repository-format=docker --location=$R
gcloud iam service-accounts create deno-api --display-name "Deno API + run job"
gcloud iam service-accounts create deno-scheduler --display-name "Deno cron"
API_SA=deno-api@$P.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $P --member serviceAccount:$API_SA --role roles/secretmanager.secretAccessor --condition=None
gcloud projects add-iam-policy-binding $P --member serviceAccount:$API_SA --role roles/run.developer --condition=None
gcloud iam service-accounts add-iam-policy-binding $API_SA --member serviceAccount:$API_SA --role roles/iam.serviceAccountUser
```
`run.developer` + `serviceAccountUser` let the API start `deno-run` executions with argument overrides
that run as `deno-api@` itself.

### 6.5 Secrets
One secret per value, read from `.env` so nothing is typed or echoed:
```bash
val() { grep -m1 "^$1=" .env | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/'; }
printf '%s' "$(val DATABASE_URL)"        | gcloud secrets create database-url    --data-file=- --replication-policy=automatic
printf '%s' "$(val NVIDIA_NIM_API_KEY)"  | gcloud secrets create nim-key         --data-file=- --replication-policy=automatic
printf '%s' "$(val SUPABASE_SECRET_KEY)" | gcloud secrets create supabase-secret --data-file=- --replication-policy=automatic
printf '%s' "$(val VALKEY_URL)"          | gcloud secrets create valkey-url      --data-file=- --replication-policy=automatic
```
Never pass secrets with `--set-env-vars`: they'd show in plain text in the console and in `describe` output.

### 6.6 SearXNG (private)
```bash
gcloud builds submit deploy/searxng --region $R --tag $R-docker.pkg.dev/$P/deno/searxng:$(git rev-parse --short HEAD)
gcloud run deploy deno-searxng --image $R-docker.pkg.dev/$P/deno/searxng:<tag> --region $R --port 8080 \
  --no-allow-unauthenticated --memory 512Mi --max-instances 2 --set-env-vars SEARXNG_SECRET=$(openssl rand -hex 16)
gcloud run services add-iam-policy-binding deno-searxng --region $R \
  --member serviceAccount:$API_SA --role roles/run.invoker
```
Then put its URL into `SEARXNG_URL` in `deploy/deploy-free.sh`.

### 6.7 API, run job, crons and web
Link the Vercel CLI once (`vercel login`), then:
```bash
bash deploy/deploy-free.sh
```
It does the following, in order:
1. Builds the API image with BuildKit (`deploy/cloudbuild-api.yaml`).
2. Creates or updates `deno-run`.
3. Deploys `deno-api` (public), then sets `CRON_OIDC_AUDIENCE` to its URL and checks `/readyz`.
4. Creates or updates the two Scheduler jobs.
5. Links the `deno-web` Vercel project and sets `NEXT_PUBLIC_SUPABASE_URL`,
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (from `web/.env.local`) and `BACKEND_URL` (the API URL).
6. Deploys to production, reads the public `*.vercel.app` alias, sets `NEXT_PUBLIC_SITE_URL`, then redeploys.
7. Sets `WEB_ORIGINS` and `APP_URL` on the API to the web URL.

### 6.8 After the first deploy
- **Vercel → Settings → Build and Deployment → Root Directory = `web`** (leave "Include files outside the
  root directory" on). Without it, Git-triggered builds run at the repo root and fail.
- **Supabase → Authentication → URL Configuration:** Site URL and Redirect URLs = the web URL (§6.1).
- Google OAuth client: authorised redirect URI `https://<ref>.supabase.co/auth/v1/callback`.
- Smoke test: sign up, confirm the email, create a project, run one validation, and watch it finish (§8).

---

## 7. Code that makes this deployment work

| What | Where | Setting |
|---|---|---|
| Graph runs as Cloud Run Job executions | `deno_core/jobs.py`, `deno_core/gcp.py`, `deno_worker/run_once.py`, `deno_worker/handlers.py` | `TASK_RUNNER=cloudrun_job`, `CLOUDRUN_JOB` |
| Cron endpoints with OIDC auth (404 when unset, hidden from OpenAPI) | `deno_api/cron.py`, `deno_core/maintenance.py` | `CRON_OIDC_AUDIENCE`, `CRON_SERVICE_ACCOUNT` |
| Google ID token on every SearXNG call (cached about 55 min) | `deno_core/gcp.py`, called from the `deno_graphs` validation and content nodes | `SEARXNG_GCP_AUTH=true` |
| TLS Redis | redis client handles `rediss://` | `VALKEY_URL` |
| Startup checks in production | `deno_core/settings.py::_production_requirements` | refuses to start without `SUPABASE_URL`, NIM key, a Postgres URL, and a full `CLOUDRUN_JOB` name |
| BuildKit image build | `deploy/cloudbuild-api.yaml` | — |
| SearXNG image with settings baked in | `deploy/searxng/Dockerfile` | `SEARXNG_SECRET` |
| No secrets uploaded to Cloud Build | `.gcloudignore` | — |
| One-command deploy | `deploy/deploy-free.sh` | — |

`TASK_RUNNER=taskiq` (the default) keeps the compose / VPS setup working unchanged: a Valkey queue, a
worker and a scheduler.

---

## 8. Operating it

```bash
G=~/google-cloud-sdk/bin/gcloud; R=asia-northeast1
# Health
curl -s https://deno-api-46vgcwltwa-an.a.run.app/readyz
# API logs (latest 100)
$G run services logs read deno-api --region $R --limit 100
# Runs: list executions, then read one execution's logs
$G run jobs executions list --job deno-run --region $R --limit 10
$G logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="deno-run"' --limit 100 --freshness 1h
# Crons: last results, or run one now
$G scheduler jobs describe deno-requeue --location $R --format='value(lastAttemptTime,status)'
$G scheduler jobs run deno-purge --location $R
# Web
vercel ls deno-web           # deployments
vercel logs <deployment-url> # runtime logs
```

**Roll back the API** to the previous revision (instant, no rebuild):
```bash
$G run revisions list --service deno-api --region $R
$G run services update-traffic deno-api --region $R --to-revisions <previous-revision>=100
$G run jobs update deno-run --region $R --image <previous image>   # keep the job on the same code
```
**Roll back the web app:** `vercel rollback` (or Vercel dashboard → Deployments → Promote).

**Rotate a secret:**
```bash
printf '%s' "$NEW_VALUE" | $G secrets versions add database-url --data-file=-
$G run services update deno-api --region $R --update-labels rotated=$(date +%s)   # new revision reads :latest
```
Job executions read `:latest` when each one starts, so no job update is needed.

**Change a plain env var:** `$G run services update deno-api --region $R --update-env-vars KEY=value`
(and `$G run jobs update deno-run --region $R --update-env-vars KEY=value` if the graph code reads it).
For the web app, `vercel env rm KEY production --yes`, then `printf '%s' value | vercel env add KEY production`, then
redeploy. `BACKEND_URL` and every `NEXT_PUBLIC_*` value are baked in at build time.

**Clean up old images** (Artifact Registry has 0.5 GB free):
`$G artifacts docker images list $R-docker.pkg.dev/deno-gtm/deno/api --include-tags`, then
`$G artifacts docker images delete <image>@<digest> --delete-tags` for old ones.

Incident procedures (failing source, NIM outage, takedowns, account deletion) are in [`runbooks.md`](runbooks.md).

---

## 9. Known gotchas (all hit during the first deploy)

| Symptom | Cause | Fix |
|---|---|---|
| `GET /healthz` returns Google's 404 page | Cloud Run's front end reserves paths ending in `z` like `/healthz` | Use `/readyz` |
| Cloud Build fails: `the --mount option requires BuildKit` | `gcloud builds submit --tag` uses the classic builder | Build with `--config deploy/cloudbuild-api.yaml` |
| `billing budgets create`: `INVALID_ARGUMENT` | Budget currency must match the billing account (INR) | `--budget-amount 100INR` |
| `alembic`: `Name or service not known` | `.env` still had the template host `aws-0-REGION…` | Paste the real session pooler URI |
| Team `*-projects.vercel.app` URL redirects to a Vercel login | Vercel Deployment Protection covers deployment and team URLs | Use the production alias `deno-web-eight.vercel.app` |
| Git pushes build at repo root and fail | Vercel Root Directory was `.` | Set it to `web` |
| Login emails link to localhost | Supabase Site URL / Redirect URLs not updated | §6.8 |
| SearXNG calls return 403 | API account lacks `run.invoker` on `deno-searxng`, or `SEARXNG_GCP_AUTH` is off | §6.6 |
| `POST /internal/cron/*` returns 404 | `CRON_OIDC_AUDIENCE` / `CRON_SERVICE_ACCOUNT` empty | Both are set by the deploy script |
| First request after idle is slow | Scale to zero, cold start | Expected on the free tier. `--min-instances 1` removes it but costs money |
| Free Supabase project paused | 7 days without activity | Restore in the dashboard; the daily purge cron normally prevents it |

Still open before a public launch: custom SMTP for auth emails, Cloudflare Turnstile on the auth form,
a separate production Supabase project (dev and prod share `bfinvyflanpjfzlisspq` today),
Stripe (§11), and CI deploys on tag with Workload Identity Federation (no JSON keys).

---

## 10. When to leave the free tier

- Supabase database near its size cap, or the 7-day pause hurts → Supabase Pro.
- You start charging → Vercel Pro (Hobby terms), or move the web app to Cloudflare Pages.
- NIM's 40 req/min becomes the bottleneck → a paid LLM provider for the strong role first.
- Steady traffic all day → one small VPS with `compose.prod.yml` (docs/08 ADR-011) becomes cheaper and
  simpler than many free quotas stitched together.

## 11. Stripe (later)

Set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` (as secrets) and `STRIPE_PRICE_PRO` on `deno-api`. The webhook
URL is `https://deno-api-46vgcwltwa-an.a.run.app/api/v1/billing/webhook`. The billing endpoints answer 503 until
these are set. `APP_URL` (already the web URL) is where Stripe sends people back after checkout.

## 12. Why not Supabase Edge Functions

Edge Functions run a JS/TS/WASM runtime, and Deno's backend is Python. Even a TypeScript rewrite wouldn't fit:
the graph runs are long-running (a validation takes about 3 minutes, longer than the free Edge Function
wall-clock limit), Redis needs a persistent server, and SearXNG is a container image. Supabase stays in the stack
for what it's good at: Postgres, pgvector and Auth.
