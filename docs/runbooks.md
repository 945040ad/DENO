# Deno runbooks

Short, do-this-now procedures. Stack: Caddy → Next.js (web) → FastAPI (api) + taskiq (worker, scheduler) →
Supabase Postgres + Valkey + SearXNG (compose.prod.yml).

> **The live deployment is the free tier** (Vercel + Cloud Run + Upstash). Its health checks, logs, rollback
> and secret rotation are in [`09_FREE_DEPLOYMENT.md` §8](09_FREE_DEPLOYMENT.md#8-operating-it). The incident
> procedures below apply to both setups; read "worker" as the `deno-run` job there.

## Health at a glance

- `curl https://$DOMAIN/api/v1/openapi.json` → 200 means Caddy, web and API are up.
- On the host: `docker compose -f compose.prod.yml exec api curl -s localhost:8000/readyz` → database and valkey `ok`.
- Metrics are not exposed publicly (only `/api/*` is proxied). Scrape `http://api:8000/metrics` (bearer
  `METRICS_TOKEN`) and `http://worker:9000` from inside the compose network.
- Key series: `deno_runs_total{status}`, `deno_run_seconds`, `deno_source_errors_total{source}`,
  `deno_llm_tokens_total`, `deno_gate_results_total{outcome}`, `deno_http_requests_total{status=~"5.."}`.

## Alerts and what to do

| Alert | Likely cause | Action |
|---|---|---|
| Runs failing (`deno_runs_total{status="failed"}` rising) | NIM outage or key limit | Check worker logs for `llm_call_failed`; NIM status; runs retry automatically (transient errors re-queue and resume from checkpoint) |
| p95 run > 4 min | NIM queue slow, a source timing out | `deno_graph_node_seconds` shows the slow node; see "Disable a failing source" |
| Source health < 70% | Source blocking or down | `select * from source_health order by window_start desc limit 20;` then disable it |
| 5xx spike | Deploy regression or DB | Roll back (below); check Sentry |
| Cost per run over budget | Prompt/loop regression | Runs stop at `LLM_RUN_TOKEN_BUDGET`; check `usage_events` by run |

## Disable a failing source

Sources are per-run `Send` branches and a failed source never fails a run. To stop calling one entirely,
remove its queries in `deno_graphs/validation/nodes.py::query_planner` (or set `PER_SOURCE_LIMIT`) and deploy;
for robots-gated hosts, remove the host from `SOURCES_ROBOTS_OPT_IN` and restart api/worker.

## Deploy and roll back

```bash
export TAG=<git sha>
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml --profile migrate run --rm migrate   # migrations are backward compatible
docker compose -f compose.prod.yml up -d
# roll back: set TAG to the previous sha and `up -d` again (downgrade migrations only if the release notes say so)
```

The worker has `stop_grace_period: 5m`, so in-flight runs finish; anything cut off is re-claimed and
resumes from its LangGraph checkpoint.

## Restore from backup

See `deploy/backup/`. `restore_drill.sh` restores the latest dump into a scratch database and verifies
it; run it monthly. To restore production, point `DATABASE_URL` at the restored database and restart
api, worker and scheduler.

## Rotate keys

| Key | Where | Steps |
|---|---|---|
| `NVIDIA_NIM_API_KEY` | build.nvidia.com | Create new key → update `.env.production` → `up -d api worker` → revoke old |
| `SUPABASE_SECRET_KEY` | Supabase dashboard → API keys | Same; only `DELETE /me` uses it |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Stripe dashboard | Roll the key; add the new webhook secret, deploy, then remove the old endpoint secret |
| `METRICS_TOKEN`, `SEARXNG_SECRET` | local | Generate with `openssl rand -hex 32`, update, restart |

## Takedown requests

`GET /api/v1/admin/takedowns?status=received` (admin only: `update profiles set role='admin' where id='…';`).
Approve with `POST /api/v1/admin/takedowns/{id}/approve` (purges matching text across all users;
citations keep the link) or reject. Target: resolve within 7 days.

## Account deletion problems

`DELETE /me` deletes data first, then the Supabase login. If the login removal fails, the log line
`auth_user_delete_failed` names the user id: delete it in the Supabase dashboard.

## SearXNG engines blocked (X / LinkedIn / Product Hunt report "search engines blocked")

Discovery for X, LinkedIn posts and Product Hunt goes through SearXNG, whose upstream engines rate-limit
a single server IP (seen in testing: Brave "too many requests", DuckDuckGo and later Google CAPTCHA after
~30 runs; Bing kept working). Check:

```bash
curl -s -G http://searxng:8080/search --data-urlencode "q=site:x.com test" --data-urlencode format=json \
  | jq '.results | length, .unresponsive_engines'
```

Runs still complete (Reddit and HN don't depend on it), but reports lose X/Product Hunt evidence. The
affected sources now fail with `unavailable: search engines blocked: brave (too many requests), …` (in the
run's `coverage.source_errors` and the `SOURCE_ERRORS{error="unavailable"}` metric) instead of silently
returning nothing, and a run that falls short because of it gets one retry and then tells the founder the
sources failed rather than that their idea lacks evidence.

Blocked answers are not cached (before 2026-10-23 they were, for 24 h, so a block kept returning nothing for
a day after it lifted - if you are on an older build, flush the `src:cache:` keys after a block clears).
Fixes, in order of effort: wait (blocks lift within hours); spread engines in `deploy/searxng/settings.yml`;
route SearXNG through a proxy pool (`outgoing.proxies`); or add a paid search API engine.

## Arctic Shift slow ("Timeout. Maybe slow down a bit", HTTP 422)

The Reddit client retries these twice with backoff. If `deno_source_errors_total{source="reddit"}` keeps
rising, Arctic Shift is overloaded: runs continue on the other sources and coverage gaps are reported
honestly in the verdict.
