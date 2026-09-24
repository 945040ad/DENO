# Deno — Production Development Plan (phase by phase)

**Requirements:** `.claude/prds/deno-flagship.prd.md`
**Research and rationale:** `docs/07_FLAGSHIP_REBUILD_AND_LAUNCH.md`
**Written for:** a solo developer; the estimates assume focused full-time weeks.

**Revision 2026-09-24:** auth moves to **hosted Supabase Auth** (ADR-003, Phase 3 rewritten; no auth tables or flows of our own), and the web client moves to **Next.js** as a pixel-perfect port of the current UI (ADR-010, new Phase 1b, Phase 11 updated). The Deno gateway is retired, and Postgres is the same hosted Supabase project (ADR-001). No Supabase containers run locally.

---

## 0. Architecture decisions (ADRs to record in `docs/adr/`)

| # | Decision | Choice | Why | Revisit if |
|---|---|---|---|---|
| ADR-001 | Primary database | **PostgreSQL + pgvector, hosted by Supabase** (the same hosted project as Auth; no local Docker Postgres) | One store for relational data, vectors, the LangGraph checkpointer (`PostgresSaver`) and full-text search (`tsvector`). Living next to `auth.users` gives real FKs and RLS on `auth.uid()`. SQLite can't handle concurrent workers | Supabase limits/cost → any Postgres 16; only the auth FK moves |
| ADR-002 | ORM / migrations | **SQLAlchemy 2.0 async + Alembic**, `asyncpg` driver | Typed, async, industry standard | — |
| ADR-003 | Auth | **Supabase Auth, hosted project** (decided 2026-09-24): email + password, email confirmation, password reset, Google OAuth (GitHub optional). Sessions are managed by `@supabase/ssr` cookies in Next.js. FastAPI verifies the Supabase access token (asymmetric JWT via the project JWKS) and uses `sub` as `user_id` | No auth code to maintain: no token tables, mailers, OAuth flows or session store | Supabase pricing at scale; migration path = export `auth.users` |
| ADR-004 | Background jobs | **taskiq** (+ taskiq-redis `RedisStreamBroker`) on **Valkey** — acknowledged delivery, re-claim of dead workers' jobs, cron scheduler (changed 2026-09-24: arq pins redis<6 and is barely maintained) | Async-native, typed, maintained | High volume → Temporal |
| ADR-005 | Agent orchestration | **LangGraph 1.2** `StateGraph` + **LangChain 1.x** (`langchain-nvidia-ai-endpoints`), structured output with Pydantic, `PostgresSaver` checkpointer (`SqliteSaver` in tests). No hand-rolled agent loops | Durable, resumable, `Send` fan-out, `interrupt()` for human approval; user requires professional-grade agent tooling | — |
| ADR-006 | Retrieval | pgvector HNSW + Postgres FTS (hybrid, RRF fusion) → reranker | No extra vector server | >5M chunks → Qdrant |
| ADR-007 | Embeddings / rerank | **`nvidia/nemotron-3-embed-1b`** (2048-d) stored as pgvector `halfvec(2048)` + **`nvidia/llama-nemotron-rerank-vl-1b-v2`** (finalised in Phase 0; older NIM rerankers are end-of-life) | Only live NIM options on this key | NIM model EOL → local BGE-M3 / bge-reranker-v2-m3 |
| ADR-008 | LLM routing | Roles `fast` / `strong` / `judge` → **`nvidia/nemotron-3-super-120b-a12b`** (1.2 s TTFT, structured output OK); fallback `meta/llama-3.2-11b-vision-instruct`. Structured output via `json_schema`, never function calling. Client limiter ≤36 req/min (NIM cap 40) | Fastest capable model measured in Phase 0 (`docs/spikes/phase0.md`) | Re-run `spikes/nim_model_bench.py` when queues change |
| ADR-009 | Social data | Keyless tiered source clients — **confirmed in Phase 0: 80% of ideas get ≥10 hydrated X/LinkedIn posts**; Apify tier optional, off by default | User constraint: no platform keys or sessions | Source health <70% |
| ADR-010 | Frontend | **Next.js 16 (App Router, TypeScript) in `web/`, a pixel-perfect port of the current editorial UI** (decided 2026-09-24). The existing `base.css` / `landing.css` / `auth.css` / `app.css` are reused byte-for-byte; HTML becomes JSX with identical markup and class names; vanilla JS becomes React state. Next.js replaces the Deno gateway as the BFF (security headers, `/api/*` rewrite to FastAPI, auth session refresh in `proxy.ts`) | Typed components, Supabase SSR auth, room for the heavier Phase 11 screens, one less service to run | — |
| ADR-011 | Deploy | Docker Compose on one VPS (Hetzner or similar) behind **Caddy** (auto-TLS); managed Postgres optional | Cheap, simple, production-capable for MVP scale | >1 node → Fly.io or k8s |
| ADR-012 | Billing | Stripe Checkout + Customer Portal + webhooks | Standard | — |
| ADR-013 | Observability | Structured JSON logs (structlog), OpenTelemetry traces, Sentry for errors, Langfuse cloud for LLM traces, Prometheus metrics + Uptime Kuma | Full coverage at low cost | — |
| ADR-014 | Packaging | `uv` + `pyproject.toml`; Python 3.12 in containers (widest wheel support for pgvector/asyncpg/Scrapling; the local 3.14 venv is dev only) | Reproducible builds | — |

---

## Definition of Done (applies to every phase)

- **Code quality:**
  - `ruff` + `ruff format` clean.
  - `mypy --strict` clean on new modules.
  - `tsc --noEmit` + ESLint clean on `web/`.
- **Tests:**
  - Test-first (`ecc:tdd-workflow`).
  - ≥80% line coverage on new code.
  - No network in unit tests; recorded fixtures only.
- **Security:**
  - Every new endpoint has an ownership check and an input schema, and appears in OpenAPI.
  - No secrets in code; config via `pydantic-settings`; startup **fails fast** on missing required settings.
- **Behaviour:**
  - Errors return the standard envelope `{error:{code,message,request_id}}` and never leak stack traces or upstream bodies.
  - Logs carry `request_id`, `user_id` and `project_id`; there is no PII in logs.
- **Data:**
  - A migration is included and reversible, and was tested up and down.
- **Review:**
  - Reviewed with `ecc:python-reviewer` / `ecc:fastapi-reviewer` (plus `ecc:security-reviewer` for auth, data or external I/O) before merge.
- **Docs:**
  - ADR or README updated when behaviour changes.

---

## Phase 0 — Feasibility spike & decisions (3 days)

**Goal:** prove or disprove keyless discovery before building on it (PRD Milestone 0).

**Status (2026-09-24): done** — see `docs/spikes/phase0.md`. Keyless discovery passes (80% ≥ 60%); models chosen; ADR-007/008/009 finalised.

**Steps:**
1. Run SearXNG in Docker (official compose), with JSON output and the limiter enabled.
2. Script `spikes/discovery_probe.py` for 10 test ideas × {`site:x.com/*/status`, `site:linkedin.com/posts`, Arctic Shift per candidate subreddit, HN}, and record hit counts.
3. Hydrate every found URL: X through syndication and oEmbed, LinkedIn through Scrapling (plain HTTP, then Camoufox). Record success rate, 999/authwall rate and latency.
4. Check NIM embed/rerank model availability and rate limits.
5. Pick models: 5 identical analyst prompts across 2–3 candidate strong models, scored manually.

**Exit criteria:**
- A written report `docs/spikes/phase0.md`.
- A decision on the Apify tier: ≥60% of ideas yield ≥10 hydrated X/LI posts → keyless only.
- ADR-007/008/009 finalised.

---

## Phase 1 — Repository & platform foundation (1 week)

**Status (2026-09-24): done.** Workspace members so far: `packages/gates`, `packages/core`, `apps/api`; the other packages are created by the phases that need them. `compose.dev.yml` runs api, web, valkey and searxng. Postgres is the hosted Supabase project (CI uses a pgvector service container).

**Restructure:**

```
deno/
  apps/
    api/                    # FastAPI (HTTP only, thin)
      deno_api/
        main.py  deps.py  errors.py  middleware.py
        routers/  auth.py projects.py runs.py content.py billing.py admin.py health.py
        schemas/            # request/response Pydantic models (API contract)
    worker/                 # arq worker entrypoint + job definitions
  packages/
    core/                   # domain: settings, logging, db models, repositories, services
    sources/                # keyless source clients (publishable OSS: deno-sources)
    rag/                    # ingest, embed, retrieve
    graphs/                 # LangGraph validation / content / trends
    gates/                  # anti-slop + voice + ban-risk (publishable OSS: deno-slop-gate)
    llm/                    # model router, prompts registry, cost accounting
  web/                      # Next.js 16 app (pixel-perfect port of ./public; also the BFF)
  supabase/                 # migrations (SQL) applied to the hosted Supabase project
  migrations/               # Alembic
  evals/                    # datasets + runners
  deploy/                   # compose files, Caddyfile, searxng settings, backup scripts
  tests/                    # unit / integration / e2e
```

**Tasks:**
- `uv` workspace, `pyproject.toml` per package, locked deps. `pre-commit` running ruff, mypy, ESLint/tsc on `web/`, gitleaks.
- `core.settings` (pydantic-settings, per-env, secret files supported); `core.logging` (structlog JSON + request-id middleware).
- Error model: domain exceptions → HTTP mapping; a global handler that never echoes internals (fixes `main.py:127`).
- Docker:
  - Multi-stage images, non-root user, healthchecks.
  - `compose.dev.yml` services: api, worker, valkey, searxng, web. Postgres and Auth are the hosted Supabase project (no Supabase containers).
  - `compose.prod.yml` adds Caddy.
- CI (GitHub Actions):
  - lint → typecheck → unit → integration (service containers: Postgres, Valkey) → build images → Trivy scan.
  - Dependabot/Renovate.
- Move the existing `engine/*` into `packages/gates` unchanged, with the 21 existing tests. Rewrite the tests that touch the real DB to use a temp DB. Mark the live tests `@pytest.mark.live`, excluded by default.

**Exit criteria:**
- `docker compose up` runs the full stack locally.
- CI is green.
- The existing behaviour is still reachable.

---

## Phase 2 — Database layer (1 week)

**Status (2026-09-24): done** — see progress.md. Checkpointer tables move to Phase 8 (they need the graph package); the purge cron is scheduled by the Phase 4 worker.

**Schema** (UUIDv7 primary keys; `created_at`/`updated_at` timestamptz UTC; soft delete via `deleted_at` where users can delete; every tenant table carries `user_id`, indexed):

| Domain | Tables |
|---|---|
| Identity | `profiles` (`id` = `auth.users.id` FK, display name, role, plan; created by an `on auth.users insert` trigger), `api_audit_log`. Users, OAuth identities and sessions live in Supabase's `auth` schema — not ours to maintain |
| Projects | `projects` (idea, status enum, user_id), `validation_runs` (status, thread_id, started/finished, cost_usd, error_code) |
| Evidence | `source_documents` (source enum, url UNIQUE per run, canonical_url, author_handle, published_at, engagement jsonb, raw_text, fetched_at, fetch_tier, content_hash), `chunks` (document_id, ordinal, text, `embedding vector(N)`, `tsv tsvector`), `queries` (the planner's queries per run, with hit counts) |
| Findings | `claims` (run_id, analyst, text, stance), `citations` (claim_id → chunk_id, entailment_score, verified bool), `signals` (run_id, name, value, method, inputs jsonb), `verdicts` (run_id, verdict enum incl. INSUFFICIENT_EVIDENCE, confidence, coverage jsonb, reasons) |
| Communities | `communities` (platform, name, url), `community_rules` (karma gate, promo policy, cadence, source_url, verified_at), `run_communities` (run_id, community_id, relevance, evidence_count) |
| Voice | `voice_samples` (user-supplied text or URL), `voice_profiles` (features jsonb, delta baseline, version), `story_bank_entries` |
| Content | `content_plans`, `content_briefs`, `content_drafts` (version, text, status enum draft/gated/approved/rejected/exported), `gate_results` (draft_id, layer, pass, findings jsonb), `hook_patterns` (formula_id, platform, topic, relative_engagement, sample_urls) |
| Billing | `subscriptions`, `usage_events` (user_id, kind, units, cost_usd), `quotas`, `stripe_events` |
| Ops | `source_health` (source, window, success_rate, p95_ms), `takedown_requests`, `feature_flags` |

**Tasks:**
- SQLAlchemy models plus a repository layer. **Every query is scoped by `user_id` at the repository level** (no raw session access from routers).
- Indexes:
  - `chunks.embedding` HNSW (cosine).
  - `chunks.tsv` GIN.
  - `source_documents(content_hash)`.
  - FKs indexed.
  - Partial indexes on active rows.
- LangGraph `PostgresSaver` tables created via its `setup()`, inside a migration.
- Row-level security on every table in `public` (Supabase exposes it through the Data API): `to authenticated using ((select auth.uid()) = user_id)`, with `with check` on update. The API still scopes queries itself; RLS is defense in depth. The worker connects with a role that bypasses RLS and always passes `user_id` explicitly.
- **Retention:**
  - Raw scraped text is purged after 90 days (configurable), keeping URL, hash and the claim links.
  - A nightly arq cron job does the purge.
- **Backups:** nightly `pg_dump` to S3-compatible storage (restic or wal-g), 30-day retention, **monthly restore drill** script.
- Seed data: the `communities` + `community_rules` table from `docs/05_…`, with `verified_at`.

**Exit criteria:**
- Migrations run up and down clean.
- Repository tests prove cross-tenant access is impossible.
- A backup/restore script has been tested once.

---

## Phase 3 — Authentication, authorisation & tenancy with Supabase Auth (4 days)

**Status (2026-09-24): done in code.** Waiting on external inputs: hosted project keys (live login test) and Cloudflare Turnstile keys.

**Status (2026-09-24): partly built.** Done: Next.js auth flows (`/auth`, callback, confirm, reset, sign-out, protected `/app`) and FastAPI `current_user` (JWKS verification) with per-user project ownership + IDOR tests. Remaining: dashboard configuration on the hosted project, Turnstile, the `profiles` table (Phase 2), rate limits, account export/delete, Playwright auth journey against the dev project.

**We write no auth protocol code.** The hosted Supabase project owns users, passwords, OAuth, email confirmation, password reset, sessions and refresh tokens. No Supabase containers run locally; dev and prod point at hosted projects (a separate dev project is recommended).

**Supabase project setup** (dashboard; settings recorded in `docs/supabase-setup.md`):
- Email + password provider, email confirmation on, minimum password length 10 (matches the current UI rule).
- Google OAuth (GitHub optional). Redirect allow-list: `http://localhost:3000/**` and the production origin only.
- Custom SMTP (Resend / Postmark) for production; the built-in mailer is rate-limited and dev-only.
- Captcha: Cloudflare Turnstile through Supabase's built-in captcha support (the `turnstile-spin` skill is available).
- Asymmetric JWT signing keys (default for new projects) so the API can verify tokens with the public JWKS.

**Next.js (`web/`), `@supabase/ssr`:**
- `lib/supabase/client.ts` (browser) and `lib/supabase/server.ts` (server components / route handlers), cookie `getAll`/`setAll` only.
- `proxy.ts` refreshes the session on every request and redirects unauthenticated users away from `/app`.
- Protect pages with `supabase.auth.getClaims()` (verifies the JWT), never `getSession()` on the server.
- Routes: `/auth` (the existing login/sign-up screen, same pixels), `/auth/confirm` (email OTP link → `verifyOtp`), `/auth/callback` (OAuth PKCE → `exchangeCodeForSession`), `/auth/reset` (set a new password), `/auth/signout` (POST).
- The browser calls FastAPI through the Next.js `/api/*` rewrite with `Authorization: Bearer <access_token>`.

**FastAPI:**
- `current_user` dependency: verify the bearer token against the Supabase JWKS (cached; `iss`, `aud=authenticated`, `exp` checked; algorithm taken from the JWK, never from the token), yielding `user_id = sub`. HS256 legacy-secret verification is available via config for older projects only.
- `require_owner(project)` on every project/run/content route → 404 on foreign ids.
- Never authorise from `user_metadata` (user-editable). Roles live in `app_metadata.role` or `profiles.role`.
- CORS limited to the web origin (fixes `main.py:35-41`).
- Rate limits (Valkey sliding window): API 60/min per user; validation runs quota-based (Phase 12). Login rate limits are Supabase's.

**Account lifecycle:**
- Data export as a JSON download.
- Account deletion: the API deletes the user's rows, then calls the Supabase admin API (`auth.admin.deleteUser`, secret key server-side only) — GDPR hard delete within 30 days. Sign the user out first; existing access tokens expire by their short TTL.

**Security headers:** set in `next.config.ts` `headers()`: CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors none.

**Tests:**
- JWT verification unit tests with locally generated keys (valid, expired, wrong issuer, wrong audience, `alg=none`, tampered signature) — no network.
- An IDOR suite: every route called with another user's token → 404.
- Playwright against the dev Supabase project: sign-up → login → `/app` → sign-out; unauthenticated `/app` → redirect to `/auth`.

**Exit criteria:**
- `ecc:security-reviewer` pass with no High findings.
- The existing screens work behind login in the Next.js app.

---

## Phase 4 — API v1, job system & streaming (1 week)

**Status (2026-09-24): done** — see progress.md. Crash-resume is verified in Phase 8 once the checkpointed graph exists. Legacy `/api/*` routes stay until the UI moves to v1 (Phase 11).

**API design:**
- `/api/v1/...` with an OpenAPI contract.
- Cursor pagination.
- An `Idempotency-Key` header on run-creating POSTs.
- The standard error envelope.
- Request size limits.

**Endpoints (MVP):**

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` · DELETE `/me` · GET `/me/export` | account |
| POST/GET/PATCH/DELETE | `/projects`, `/projects/{id}` | projects |
| POST | `/projects/{id}/runs` → 202 `{run_id}` | enqueue validation |
| GET | `/runs/{id}` · `/runs/{id}/events` (SSE) · POST `/runs/{id}/cancel` | status and stream |
| GET | `/runs/{id}/report`, `/runs/{id}/evidence?source=&cursor=`, `/runs/{id}/claims/{claim_id}` | results and evidence explorer |
| POST | `/runs/{id}/resume` | answer a LangGraph `interrupt()` |
| POST/GET | `/voice/samples`, `/voice/profile` | voice |
| POST/GET | `/story-bank` | stories |
| POST | `/projects/{id}/content-plans` → 202 · GET `/content-plans/{id}` · SSE `/content-plans/{id}/events` | content |
| PATCH | `/drafts/{id}` (edit → re-gate) · POST `/drafts/{id}/approve` · POST `/drafts/{id}/export` | human-in-the-loop |
| POST | `/audit/text` | stand-alone gate audit (free tool, rate-limited) |
| POST | `/billing/checkout`, `/billing/portal`, `/billing/webhook` | Stripe |
| GET | `/healthz` (liveness), `/readyz` (DB, Valkey, SearXNG) | ops |

**Jobs:**
- An arq worker runs graphs by `thread_id = run_id`.
- A job row tracks state; retries with backoff apply to transient errors only.
- Cancellation is cooperative (checked between nodes).
- Per-user concurrency limit: 1 active run on free, 3 on paid.
- **Resumable after a crash** through the LangGraph checkpointer.

**SSE:**
- The worker publishes node events to a Valkey stream `run:{id}`, and the API relays them.
- Heartbeat every 15 s; `Last-Event-ID` resume.
- The stream closes on the terminal state; a 404 for unknown or foreign runs.
- **Delete the in-memory `project_progress` dict** (fixes the forever-loop and the multi-worker bug).

**Exit criteria:**
- The contract tests pass (schemathesis against OpenAPI).
- Killing a worker mid-run → the run resumes.
- Two concurrent runs stream to the correct clients.

---

## Phase 5 — Keyless source layer (2 weeks)

**Contract** (`packages/sources/base.py`):
- `Post` has the fields: `source, url, canonical_url, author_handle, published_at, text, engagement{likes,comments,shares,score}, community, fetched_at, tier`.
- `SourceClient` provides `search(query, since, limit)` and `hydrate(url)`.
- Shared behaviour: an async `httpx` client, a per-host token-bucket limiter, a Valkey-backed cache (TTL per source), retries on 408/429/5xx with jitter that honour `Retry-After` and `X-RateLimit-Reset`, and a circuit breaker per source that writes to `source_health`.

**Clients:**

| Client | Discovery | Hydration | Notes |
|---|---|---|---|
| `reddit` | Arctic Shift `posts/search` + `comments/search` per candidate subreddit; `new/.rss`, `top/.rss` listings | Arctic Shift by id | Subreddit candidates come from the planner + a seeded community table |
| `x` | SearXNG `site:x.com "<q>"` → status ids | `cdn.syndication.twimg.com/tweet-result` → oEmbed fallback | Known-ID only |
| `linkedin_posts` | SearXNG `site:linkedin.com/posts "<q>"` | Scrapling HTTP → Camoufox fallback; parse OG/JSON-LD | Low volume; stop on 999/authwall |
| `linkedin_jobs` | `jobs-guest/.../search?keywords=` | card parse | Demand signal |
| `hn` | Algolia search (stories + comments) | item API | — |
| `producthunt` | `/feed` + SearXNG `site:producthunt.com/products` | page OG | Competitors |
| `trends` | Google Trends RSS | — | Context only |
| `apify` (optional) | Same actors as linkedin-skills/x-skills | — | Enabled only if `APIFY_TOKEN` is set |

**Compliance built in:**
- A descriptive User-Agent.
- robots.txt respected where applicable.
- Global per-source daily caps.
- **Fetching only on user-initiated runs**, never by crawling.
- A takedown endpoint and process (`takedown_requests`): purge by URL or author.

**Security:**
- All fetched text is **untrusted**: stored as data and never executed.
- HTML is sanitised before any UI rendering.
- An SSRF guard: allow-listed hosts only, no redirects to private IPs.

**Tests:**
- Recorded fixtures per client (pytest-recording).
- Parser tests on saved HTML/JSON.
- `scripts/probe_sources.py` live smoke test, run nightly in CI as a non-blocking alert.

**Exit criteria:**
- Every client passes its fixture tests.
- The live probe report shows each source healthy, or degraded with a working fallback.

---

## Phase 6 — RAG layer (1 week)

**Ingest pipeline:**
1. Normalise: unicode, strip boilerplate, language detect (keep EN for MVP).
2. Dedupe by `content_hash` and canonical URL.
3. Chunk: posts are usually a single chunk; long threads and articles are split recursively at ~400 tokens with ~60 overlap, keeping the parent document id.
4. Embed in batches; store in `chunks`.

**Retrieval:**
- Hybrid: pgvector top-k (50) + Postgres FTS top-k (50) → reciprocal-rank fusion → rerank top 20 → return with `chunk_id`, `document_id`, `url`, `source`.
- Filters: `run_id`, source, date window, minimum engagement.
- Per-analyst query templates (pain, demand, competitors, ICP, WTP).

**Quality:**
- A labelled eval set `evals/retrieval/` (20 ideas × expected relevant URLs).
- Metrics: recall@10, MRR, nDCG. CI fails if they regress by more than 5%.

**Exit criteria:** recall@10 ≥ 0.8 on the eval set; p95 retrieval < 300 ms.

---

## Phase 7 — LLM layer (4 days, parallel with Phase 6)

**Model router:**
- `llm.get_model(role)`, where the roles are `fast`, `strong` and `judge`. It is config-driven and built on LangChain `init_chat_model`.
- A timeout per role and a fallback model per role.

**Structured output** everywhere (`with_structured_output(PydanticModel)`), which deletes the regex JSON extraction.

**Prompt registry:**
- Versioned prompt files in `packages/llm/prompts/`, with the id and version logged per call.
- Few-shot examples stored alongside.

**Prompt-injection defense:**
- Scraped content is wrapped in delimited `<untrusted_source id=…>` blocks, with a system instruction that it is data (see `linkedin-skills/references/untrusted-content.md`).
- Analyst nodes have **no tools**.
- Outputs are schema-validated; any URL in output that is not in retrieved chunks makes it fail.

**Cost accounting:** tokens and cost per call → `usage_events`; per-run budget with a hard stop.

**Caching:** a semantic/exact cache for planner and classifier calls.

**Exit criteria:** every model call is traced (Langfuse) with cost; switching provider is a config change only.

---

## Phase 8 — Validation graph (2 weeks)

**Graph:** `packages/graphs/validation.py`, a `StateGraph` with the `PostgresSaver` checkpointer.

```
intake ─► perspective_planner ─► query_planner
      ─► [Send] collect_{reddit,x,linkedin_posts,linkedin_jobs,hn,producthunt,trends}
      ─► ingest ─► coverage_check ──(too little evidence)──► verdict(INSUFFICIENT_EVIDENCE)
      ─► [Send] analyst_{pain,demand,competitors,icp,wtp,risks,communities}
      ─► citation_validator ─► signal_scorer ─► critic ⇄ refiner (≤2) ─► verdict ─► interrupt(review) ─► finalize
```

**Nodes:**
- `intake`: structure the idea (problem, ICP, category, keywords) and reject empty or unsafe input.
- `perspective_planner` (STORM): 4–6 perspectives (buyer, user, competitor, skeptic, investor) → questions.
- `query_planner`: per-source queries and candidate subreddits; stored in `queries`.
- `collect_*`: source clients via `Send`, each with a per-source timeout. Partial failures are recorded but don't abort the run.
- `coverage_check`: document count per source, source diversity, recency. Below the threshold it short-circuits to an honest "insufficient evidence" with the gaps listed.
- `analyst_*`: retrieve → produce claims that **may only reference chunk ids**. Schema: `{claim, stance, chunk_ids[]}`.
- `citation_validator`: an entailment check (judge model, NLI-style prompt) per claim/chunk pair. Unsupported claims are dropped and logged. Any URL not in the store → hard failure.
- `signal_scorer` (**deterministic Python, no LLM**):
  - mention volume and 90-day slope
  - engagement-weighted pain (score ÷ community median)
  - WTP phrase count
  - LinkedIn job count
  - competitor frequency
  - PH launches in 12 months
  - community concentration
- `critic` ⇄ `refiner`: adversarial pass limited to cited claims; at most 2 rounds.
- `verdict`: the rule-based band from signals + the LLM rationale restricted to validated claims.
  - `confidence = f(coverage, diversity, agreement)`, clamped 0–1.
  - The enum includes `INSUFFICIENT_EVIDENCE`.
- `interrupt(review)`: the founder can flag a claim as wrong → feedback is stored for evals.

**Persistence:** each node writes to its tables (`claims`, `citations`, `signals`, `verdicts`, `run_communities`), so the report is rebuilt from the DB, not from graph state.

**Evals** (`evals/validation/`):
- 30 ideas: 10 known-good, 10 known-dead, 10 junk.
- Metrics:
  - citation precision (≥0.9)
  - fabricated URLs (=0)
  - junk → INSUFFICIENT (≥90%)
  - verdict agreement with a human label (tracked)
  - Ragas faithfulness

**Exit criteria:**
- The eval thresholds are met.
- p95 ≤ 4 min.
- The old `validation_pipeline.py` is deleted.

---

## Phase 9 — Content gates library (1 week) → open-source `deno-slop-gate`

**Layers** (each is a pure function `(text, ctx) → GateResult{pass, findings[{rule_id, span, quote, fix}]}`):

| Layer | Source | Notes |
|---|---|---|
| L1 Scrub | linkedin-humanizer FORENSIC rules | Model leakage, placeholders, em-dash rate; auto-fix where safe |
| L2 Hard-fail patterns | no-ai-slop cut lists + humanizer STRICT + existing `anti_slop.py` (add the 2 missing rules, report **all** matches) | Regex table with per-rule tests |
| L3 Density | humanizer `score_paragraph()` + existing `density_scorer.py` | Per-paragraph thresholds |
| L4 Structure | triads, contrasts, fragments, rhythm variance, specificity-near-abstraction | Deterministic |
| L5 Judge | the 20 checks from no-ai-slop `eval.md` + an over-correction check | LLM, JSON output, runs only if L1–L4 pass |
| Voice | Stylometry v2: real Burrows' Delta (z-scores over a reference corpus, top-150 MFW) against the user's profile; pass if within the user's own intra-sample spread | Rewrite of `stylometry.py:85-98` |
| Ban risk | `ban_risk.py`, reading `community_rules` from the DB instead of hard-coded rules; drop the fake `ai_detection_probability` | — |

**Tests:**
- A golden corpus: 50 human posts that must pass and 50 slop posts that must fail.
- Per-rule unit tests.
- A false-positive rate ≤10% on the human corpus.

**Packaging:** `packages/gates` published to PyPI as MIT, with a README crediting petergyang/no-ai-slop and sergebulaev/linkedin-skills.

---

## Phase 10 — Trend miner, voice & content graph (2 weeks)

**Trends subgraph:**
- Top posts from the last 30 days in the run's communities (Reddit via Arctic Shift, HN, and X/LinkedIn through discovery + hydrate).
- Hook classifier: an LLM labels F1–F20 using the linkedin-hook-extractor rules.
- Rank per topic by engagement ÷ author or community median.
- Stored in `hook_patterns` with sample URLs, cached for 24 h per community.

**Voice onboarding:**
- The user pastes 5–20 of their own posts or submits public URLs to hydrate.
- Build `voice_profiles` (features + Delta baseline + a few-shot set).
- Story Bank interview flow, the only allowed source of anecdotes and numbers.

**Content graph:**

```
brief_planner(verdict, communities, hook_patterns, story_bank)
  ─► [Send] per post: draft ─► L1–L4 ─(fail: rewrite failing spans, ≤2)─► L5 judge ─► voice ─► ban_risk
  ─► assemble_plan ─► interrupt(approve/edit per draft) ─► export (copy + deep link; never post)
```

- **Cadence respects** the community cadence caps and the 9:1 value-to-promo ratio from `community_rules`.
- An edited draft is re-gated automatically, and the diff is stored for learning.

**Evals:**
- A blind A/B of 30 new vs v1 outputs rated by humans (target ≥70% prefer new).
- Gate pass-rate ≥90% within 2 rewrites.

**Exit criteria:** thresholds met; the old `content_pipeline.py` is deleted.

---

## Phase 1b — Next.js web shell, pixel-perfect port (4 days, runs alongside Phases 1–3)

**Goal:** the current UI (landing, auth, workspace) running in Next.js with **zero visual difference**, wired to Supabase Auth.

**Status (2026-09-24): built** in `web/`. The pixel diff against `public/` shows 0 px on all 12 page×width combinations and on the interactive states (menu, accordions, FAQ, auth errors/modes). Build, types and lint are clean. Remaining: log in against the real hosted project once keys are provided, then delete `public/` and `gateway/`.

**Rules for pixel parity:**
- `public/base.css`, `landing.css`, `auth.css`, `app.css` are copied into `web/styles/` **unchanged**. No Tailwind, no CSS modules, no renamed classes.
- Markup is ported element for element: same tags, same class names, same inline styles (as React style objects), same text.
- Fonts load from the same Google Fonts URL (not `next/font`, which renames the font families and changes fallback metrics).
- Each page keeps its own stylesheet set through **route groups with separate root layouts** — `(marketing)` → base+landing, `(auth)` → base+auth, `(workspace)` → base+app — so `body` backgrounds and page CSS never leak between pages.
- Vanilla JS behaviour becomes React state with the same timing (mega menu, accordions, scroll reveal, password strength, error nudge, SSE progress, 400 ms debounced re-audit, toast).
- `innerHTML` rendering of API data is replaced by JSX (removes the XSS in `app.js`).

**Routes:** `/` (landing) · `/auth` (`?mode=signup`) · `/app` (workspace, protected) · `/auth/confirm` · `/auth/callback` · `/auth/reset` · `/auth/signout`.

**Verification:** Playwright screenshots of `public/*.html` (served statically) vs the Next.js routes at 1440, 1024 and 390 px, diffed with `pixelmatch`; the target is a 0-pixel diff outside dynamic content.

**Exit criteria:** screenshot diff clean; `next build`, `tsc`, lint clean; login/sign-up work against the hosted Supabase dev project. Then `public/` and `gateway/` are deleted.

---

## Phase 11 — Frontend screens (2 weeks)

- Built in the Next.js app from Phase 1b, reusing the editorial design system (new CSS goes in new files that use `base.css` tokens; the existing files stay untouched).
- A typed API client generated from OpenAPI (`openapi-typescript` + `openapi-fetch`) that attaches the Supabase access token.
- **Screens:**
  1. Auth (done in 1b)
  2. Projects list
  3. Idea intake
  4. Live run view (SSE timeline per node and source, with partial-evidence badges)
  5. **Verdict report**: every claim has citation chips → evidence drawer showing the real post (text, author, date, engagement, open-original link)
  6. **Evidence explorer**: filter by source, community, date, stance
  7. Communities with rules
  8. Voice onboarding + Story Bank
  9. Content plan calendar
  10. **Draft editor with gate diff** (what was flagged → the fix; live re-gate on edit, debounced)
  11. Billing / account / data export / delete
- **Accessibility:** WCAG 2.2 AA (`ecc:a11y-architect` review), keyboard navigation, focus states, reduced motion.
- **Performance:** Lighthouse ≥90 on all categories; server components by default, client components only where there's interaction.
- **E2E:** Playwright journeys (signup → run → verdict → plan → approve → export) via `ecc:e2e-runner`.

---

## Phase 12 — Billing, quotas & plans (4 days)

- Stripe Checkout (subscriptions), Customer Portal, and webhooks with signature verification and idempotent event handling (`stripe_events` table).
- Plans (pricing TBD in the PRD open questions):
  - **Free:** N validation runs/month, 7-day plan, audit tool.
  - **Pro:** more runs, 30-day plans, priority queue.
- Quota enforcement happens in one service, checked at run enqueue. `usage_events` is the ledger; there's an admin override.
- Dunning via Stripe; downgrade on failed payment keeps the data read-only.

---

## Phase 13 — Observability, reliability & security hardening (1 week)

**Observability:**
- OpenTelemetry traces across web (Next.js) → api → worker → graph nodes → source calls.
- Sentry (API, worker, web).
- Langfuse for every LLM call.
- Prometheus metrics:
  - request rate, errors, latency
  - run duration per node
  - source success rate
  - gate pass rate
  - LLM cost per run
- Grafana dashboards.
- Uptime Kuma on `/healthz` and `/readyz`.

**SLOs and alerts:**
- API availability 99.5%.
- Run success ≥95%.
- p95 run ≤4 min.
- Alerts on source health <70%, cost per run over budget, and error spikes.

**Reliability:**
- Graceful shutdown (drain workers).
- DB connection pooling (pgbouncer if needed).
- Timeouts on every external call.
- A load test (k6/Locust): 50 concurrent users, 10 concurrent runs.
- A chaos check: kill a source → the run completes with partial evidence.

**Security:**
- `/security-review` + `ecc:security-reviewer` full pass.
- Dependency audit (pip-audit, `npm audit` on `web/`).
- Container scan.
- Secrets rotation doc.
- OWASP ASVS L1 checklist.
- Privacy policy, ToS and data-retention page; takedown contact.

**Runbooks:** incident response, restore from backup, rotate keys, disable a failing source (feature flag).

---

## Phase 14 — Launch readiness & continuous evals (ongoing from week 12)

- **CI eval gate:** retrieval, validation and gates evals on every PR touching `rag/`, `graphs/`, `gates/` or `llm/`; the merge is blocked on regression.
- **Feedback loop:** user "this claim is wrong" and draft edits → weekly review → the eval set grows.
- **Feature flags** for sources and models (`feature_flags` table).
- **Staging environment** with prod-like data (anonymised), deployed on merge to `main`; prod is promoted by tag.
- **Launch checklist** per `docs/07` §10: waitlist, open-source packages published, the dogfood run published, Show HN / PH / Reddit sequence.

---

## Timeline summary (solo, full time)

| Weeks | Phases | Milestone (PRD) |
|---|---|---|
| 1 | 0 | M0 feasibility |
| 2–4 | 1, 1b, 2, 3 | M1 secure foundation |
| 5–7 | 4, 5, 6, 7 | M2 real evidence |
| 8–9 | 8 | M3 grounded verdict |
| 10–12 | 9, 10 | M4 human-voice content |
| 13–14 | 11 | M5 product experience |
| 15 | 12, 13 | M6 paid, M7 launch-ready |
| 16 | 14 + launch | Launch |

Phases 6 and 7 run in parallel. Phase 9 (gates) can start any time after Phase 1, since it has no dependencies. It's the best candidate to ship first as open source for early GitHub stars.

---

## Traceability: v1 problems → fixing phase

| v1 problem (docs/07 §1) | Fixed in |
|---|---|
| LLM-invented/hard-coded URLs, fixed quotes, identical communities | 5, 6, 8 |
| Unclamped fake confidence | 8 |
| Fake LangGraph | 8, 10 |
| Gates don't gate | 9, 10 |
| Non-standard Burrows' Delta | 9 |
| No auth, `*` CORS with credentials, error leakage | 1, 3 (Supabase Auth) |
| Blocking I/O, SSE forever-loop, shared-callback cross-talk | 1, 2, 4 |
| SQLite FKs off, no indexes, duplicate rows | 2 |
| No packaging, tests hitting the real DB/LLM | 1 |
| Gateway forwards Host | 1b (Deno gateway retired; Next.js is the BFF) |
