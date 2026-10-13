# Deno — Free-Tier Deployment Plan (no VPS)

**Status:** code ready (2026-10-06, §4); not deployed yet. Replaces the single-VPS deploy (docs/08 ADR-011) while
Deno has no revenue. Move back to a VPS, or to paid tiers, once usage outgrows the free quotas.

**Goal:** run the whole product for $0/month with no server to manage, and keep the Python
backend (FastAPI, LangGraph, NumPy) exactly as it is.

---

## 1. Why not Supabase Edge Functions

Edge Functions run Deno's JS/TS/WASM runtime only. Deno's backend is Python (`uvicorn
deno_api.main:app`), so it can't run there. Even rewritten in TypeScript, three parts don't fit:

- The taskiq **worker** and **scheduler** are long-running processes. Edge Functions are short,
  request-triggered calls.
- **Valkey** needs a persistent server. Supabase provides Postgres, not Redis.
- **SearXNG** is a container image. Edge Functions can't run images.

A validation run takes about 3 minutes, which is also longer than the free Edge Function
wall-clock limit. Supabase stays in the stack for what it's good at: Postgres, pgvector and Auth.

---

## 2. Target layout

| Piece | Free home | What changes |
|---|---|---|
| Next.js web (`web/`) | **Vercel Hobby** | Nothing. Root directory `web`, set the env vars below |
| Postgres + pgvector + Auth | **Supabase Free** (already in use) | Nothing |
| FastAPI API (`Dockerfile`) | **Google Cloud Run** service `deno-api` | Same image |
| Graph runs (today: taskiq worker) | **Cloud Run Job** `deno-run`, one execution per run | Same image (§4.1) |
| Cron jobs (today: taskiq scheduler) | **Cloud Scheduler** → authenticated API endpoints | Two small endpoints |
| Valkey | **Upstash Redis** free tier | Only `VALKEY_URL` (use `rediss://`) |
| SearXNG | Cloud Run service `deno-searxng` (private) | `deploy/searxng/Dockerfile` |
| LLM | NVIDIA NIM (already free) | Nothing |
| Errors / traces | Sentry free, Langfuse cloud free | Nothing |

```
browser ──► Vercel (Next.js) ──/api/*──► Cloud Run: deno-api ──► Supabase Postgres (session pooler)
                                              │  ├──► Upstash Redis (rate limits, run events)
Cloud Scheduler ──(OIDC)──► /internal/cron/*  │  ├──► Cloud Run: deno-searxng
                                              │  └──► NVIDIA NIM
```

---

## 3. Free-tier limits to know

Check each provider's pricing page before launch; quotas change.

- **Supabase Free:** the project **pauses after 7 days with no activity**, and has a small
  database size cap (500 MB at the time of writing). The nightly purge cron counts as activity.
  You get two free projects, so use one for dev and one for prod.
- **Cloud Run:** a monthly free allowance of requests, vCPU-seconds and GiB-seconds, and it scales
  to zero. Cold starts take a few seconds. A billing account is required even if the bill is $0, so
  **set a budget alert at $1**.
- **Vercel Hobby:** non-commercial use only. Once you charge money, the terms require Pro
  ($20/mo). Alternatives: Cloudflare Pages via `@opennextjs/cloudflare`, or Netlify free.
- **Upstash Free:** capped commands per month. A taskiq worker polling the broker would burn
  through it, which is one more reason to drop the broker (§4).
- **NVIDIA NIM:** 40 req/min, shared by every user. This, not hosting, is the first real limit.

---

## 4. What the code does for this deploy (done 2026-10-06)

### 4.1 Graph runs without a worker: `TASK_RUNNER=cloudrun_job`

Cloud Run only gives an instance CPU while it handles a request, so a taskiq worker waiting on a
queue doesn't fit the free tier. With `TASK_RUNNER=cloudrun_job`, `deno_core.jobs.enqueue` starts
one execution of the Cloud Run Job named in `CLOUDRUN_JOB` (Admin API `jobs/…:run`, token from
the metadata server) instead of sending a queue message. The execution runs:

```
python -m deno_worker.run_once validation.run '{"run_id": "…", "user_id": "…"}'
```

- Same image as the API. Progress still flows through Redis to the SSE endpoint, so the web client
  doesn't change.
- Exit code 1 on a transient error (NIM queue, rate limit) → Cloud Run retries the execution
  (`--max-retries`) and the graph resumes from its LangGraph checkpoint. The Redis run lease stops
  two executions of the same run.
- Exit 0 when a run ends, including runs that end as `failed`; exit 2 on a bad invocation.
- `TASK_RUNNER=taskiq` (the default) keeps compose / VPS working exactly as before.

### 4.2 Cron without the taskiq scheduler: `/internal/cron/*`

| Task | taskiq (compose) | Free deploy |
|---|---|---|
| Purge scraped text past retention | `17 3 * * *` | Cloud Scheduler daily → `POST /internal/cron/purge` |
| Re-send runs whose enqueue was lost | every minute | Cloud Scheduler every 5 min → `POST /internal/cron/requeue` |

Both run inside the API (they're quick database queries), so no job execution is spent on them.
The endpoints accept only a Google-signed OIDC token with `aud = CRON_OIDC_AUDIENCE` and
`email = CRON_SERVICE_ACCOUNT` (verified e-mail). With those settings empty they answer 404 and
are not in the OpenAPI schema. Cloud Scheduler gives 3 free jobs per billing account.

### 4.3 Smaller pieces

- **Upstash:** `VALKEY_URL=rediss://…` works as is (TLS URLs are handled by the redis client).
- **Private SearXNG:** `SEARXNG_GCP_AUTH=true` makes every SearXNG request carry a Google ID token
  for `SEARXNG_URL` (from the metadata server, cached for ~55 min).
- **Port:** the image listens on 8000; deploy with `--port 8000`.
- `WEB_ORIGINS` = the web domain. `APP_URL` = the public web URL.

New settings (all in `.env.example`): `TASK_RUNNER`, `CLOUDRUN_JOB`, `CRON_OIDC_AUDIENCE`,
`CRON_SERVICE_ACCOUNT`, `SEARXNG_GCP_AUTH`. Production refuses to start with
`TASK_RUNNER=cloudrun_job` and no full `projects/…/locations/…/jobs/…` name.

---

## 5. One-time setup

### 5.1 Supabase (prod project)

1. Create a second project for production (keep the current one for development).
2. Enable the Auth providers and redirect URLs as in `docs/supabase-setup.md`, with the Vercel
   domain.
3. Dashboard → **Connect → Session pooler** (port 5432, IPv4). Change the scheme to
   `postgresql+asyncpg://`. Don't use the direct `db.<ref>.supabase.co` host: it is IPv6-only and
   Cloud Run egress is IPv4.
4. Run the migrations once from your machine:
   ```bash
   DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres' \
     uv run alembic upgrade head
   ```

### 5.2 Google Cloud

```bash
gcloud projects create deno-prod && gcloud config set project deno-prod
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create deno --repository-format=docker --location=us-central1

# Service accounts: one for the API and job, one for Cloud Scheduler
gcloud iam service-accounts create deno-api
gcloud iam service-accounts create deno-scheduler
API_SA=deno-api@deno-prod.iam.gserviceaccount.com
SCHED_SA=deno-scheduler@deno-prod.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding deno-prod --member serviceAccount:$API_SA \
  --role roles/secretmanager.secretAccessor
# The API starts job executions with argument overrides (run.jobs.runWithOverrides)…
gcloud projects add-iam-policy-binding deno-prod --member serviceAccount:$API_SA --role roles/run.developer
# …that run as deno-api itself.
gcloud iam service-accounts add-iam-policy-binding $API_SA --member serviceAccount:$API_SA \
  --role roles/iam.serviceAccountUser

# Secrets (one per value; never pass them as plain --set-env-vars)
printf '%s' "$DATABASE_URL"       | gcloud secrets create database-url --data-file=-
printf '%s' "$NVIDIA_NIM_API_KEY" | gcloud secrets create nim-key --data-file=-
printf '%s' "$VALKEY_URL"         | gcloud secrets create valkey-url --data-file=-
printf '%s' "$SUPABASE_SECRET_KEY" | gcloud secrets create supabase-secret --data-file=-
```

Pick the Cloud Run region closest to the Supabase project's region. Every request makes several
database round trips, so cross-region latency adds up.

### 5.3 SearXNG on Cloud Run

```bash
gcloud builds submit deploy/searxng --tag us-central1-docker.pkg.dev/deno-prod/deno/searxng
gcloud run deploy deno-searxng --image us-central1-docker.pkg.dev/deno-prod/deno/searxng \
  --region us-central1 --port 8080 --no-allow-unauthenticated \
  --set-env-vars SEARXNG_SECRET=$(openssl rand -hex 16)
```

Keep it private and let the API's service account call it:
`gcloud run services add-iam-policy-binding deno-searxng --region us-central1 --member serviceAccount:$API_SA --role roles/run.invoker`.
Set `SEARXNG_GCP_AUTH=true` on the API and the job (§4.3).

### 5.4 API, run job and scheduler

```bash
IMAGE=us-central1-docker.pkg.dev/deno-prod/deno/api:$TAG
gcloud builds submit . --tag $IMAGE
ENV="ENVIRONMENT=production,SUPABASE_URL=https://<ref>.supabase.co,WEB_ORIGINS=https://<web-domain>,APP_URL=https://<web-domain>,SEARXNG_URL=https://deno-searxng-<hash>.run.app,SEARXNG_GCP_AUTH=true"
SECRETS="DATABASE_URL=database-url:latest,NVIDIA_NIM_API_KEY=nim-key:latest,VALKEY_URL=valkey-url:latest,SUPABASE_SECRET_KEY=supabase-secret:latest"

# Graph runs: one execution per run, retried on transient failures
gcloud run jobs create deno-run --image $IMAGE --region us-central1 --service-account $API_SA \
  --command python --args=-m,deno_worker.run_once --max-retries 2 --task-timeout 30m --memory 1Gi \
  --set-env-vars $ENV --set-secrets $SECRETS

# API
gcloud run deploy deno-api --image $IMAGE --region us-central1 --service-account $API_SA \
  --port 8000 --allow-unauthenticated --min-instances 0 --max-instances 2 --timeout 3600 --memory 1Gi \
  --set-env-vars "$ENV,TASK_RUNNER=cloudrun_job,CLOUDRUN_JOB=projects/deno-prod/locations/us-central1/jobs/deno-run,CRON_SERVICE_ACCOUNT=$SCHED_SA" \
  --set-secrets $SECRETS
API_URL=$(gcloud run services describe deno-api --region us-central1 --format 'value(status.url)')
gcloud run services update deno-api --region us-central1 --update-env-vars CRON_OIDC_AUDIENCE=$API_URL

# Cron (OIDC token for the scheduler account, audience = the API URL)
gcloud scheduler jobs create http deno-purge --location us-central1 --schedule "17 3 * * *" \
  --http-method POST --uri $API_URL/internal/cron/purge \
  --oidc-service-account-email $SCHED_SA --oidc-token-audience $API_URL
gcloud scheduler jobs create http deno-requeue --location us-central1 --schedule "*/5 * * * *" \
  --http-method POST --uri $API_URL/internal/cron/requeue \
  --oidc-service-account-email $SCHED_SA --oidc-token-audience $API_URL
```

On each release, update both: `gcloud run deploy deno-api --image $IMAGE …` and
`gcloud run jobs update deno-run --image $IMAGE --region us-central1`.

`--max-instances 2` caps spend and keeps the Supabase connection count low (each instance opens up
to 15 pooled connections, see `deno_core/db/session.py`).

### 5.5 Web on Vercel

- Import the repo, **Root Directory = `web`**.
- Env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`,
  `NEXT_PUBLIC_SITE_URL=https://<web-domain>`, `BACKEND_URL=https://deno-api-<hash>.run.app`.
- Check that SSE progress streams through the `/api/*` proxy without buffering. If it doesn't,
  have the browser call the API origin directly (it's already in `WEB_ORIGINS` for CORS).

### 5.6 Stripe

Webhook URL: `https://deno-api-<hash>.run.app/api/v1/billing/webhook` (or the custom domain).

---

## 6. Checklist

- [x] §4.1 graph runs as Cloud Run Job executions (`TASK_RUNNER=cloudrun_job`)
- [x] §4.2 `/internal/cron/purge` and `/internal/cron/requeue` with OIDC auth
- [x] §4.3 `rediss://`, private SearXNG ID token
- [x] `deploy/searxng/Dockerfile` with the settings baked in
- [ ] Prod Supabase project: custom SMTP, TOTP on, migrations applied (`docs/supabase-setup.md`)
- [ ] Cloud Run service + job + scheduler (§5.4), $1 budget alert
- [ ] Vercel deploy, SSE verified end to end
- [ ] One full idea → verdict → plan run on production
- [ ] CI: build and deploy on tag (Workload Identity Federation, no JSON keys)

## 7. When to leave the free tier

- Supabase DB near its size cap, or the 7-day pause is hurting → Supabase Pro.
- You start charging → Vercel Pro (Hobby terms), or move the web app to Cloudflare Pages.
- NIM's 40 req/min becomes the bottleneck → a paid LLM provider for the strong role first.
- Steady traffic all day → a single small VPS (docs/08 ADR-011, `compose.prod.yml`) becomes
  cheaper and simpler than many free quotas stitched together.
