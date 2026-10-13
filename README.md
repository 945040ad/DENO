# Deno — Founder Go-To-Market Workspace

> **"Deno tells you if your idea is worth building — then gives you everything you need to get your first users, for free channels, in your own voice, without getting banned."**

**Live:** https://deno-web-eight.vercel.app

---

## Overview

Deno is a hybrid-architecture founder workspace designed for 2026 platform reality. It addresses the two sequential walls every founder faces:
1. **Stage 1 (Validation — Free):** An 8-agent adversarial DAG that stress-tests a startup idea, bottom-up sizes the market (TAM/SAM/SOM), identifies competitors with clickable sources, and maps the exact target subreddits and social communities with live rules.
2. **Stage 2 (Distribution — $20/mo):** A 30-day voice-matched content engine that produces platform-safe posts, hooks, and video scripts. Every single post carries a **Ban Risk Score (0–100)** powered by Peter Yang's 18 anti-slop rules (`petergyang/no-ai-slop`) and Serge Bulaev's 2026 vocabulary density heuristics (`sergebulaev/linkedin-skills`).

**Non-negotiable design constraint:** Deno never posts, votes, or messages automatically. A human always reviews and presses send (copy & deep-link).

---

## Technology Stack

| Layer | Technology |
|---|---|
| Web | Next.js 16 + React 19 (TypeScript), Supabase Auth via `@supabase/ssr` — on **Vercel** |
| API | Python 3.12, FastAPI, Pydantic v2 — on **Google Cloud Run** |
| Agents | LangGraph + LangChain, Postgres checkpointer — one **Cloud Run Job** execution per run |
| LLM | NVIDIA NIM (Nemotron 3 Super 120B, Llama 3.2 11B fallback, Nemotron embed/rerank) |
| Data | **Supabase** Postgres + pgvector (SQLAlchemy async, Alembic); **Upstash** Redis |
| Search | Self-hosted SearXNG (private Cloud Run service) + keyless sources |

Full breakdown: [`docs/11_TECH_STACK.md`](docs/11_TECH_STACK.md).

---

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/09_FREE_DEPLOYMENT.md`](docs/09_FREE_DEPLOYMENT.md) | **How it's deployed and how to deploy** — live URLs, resources, from-scratch setup, releases, rollback, gotchas |
| [`docs/10_CONFIGURATION.md`](docs/10_CONFIGURATION.md) | **Every environment variable** — backend, web, secrets, prod values |
| [`docs/11_TECH_STACK.md`](docs/11_TECH_STACK.md) | Stack, repo layout, request paths, local development |
| [`docs/supabase-setup.md`](docs/supabase-setup.md) | Supabase Auth settings and keys |
| [`docs/runbooks.md`](docs/runbooks.md) | Incident procedures |
| [`docs/01_PRD.md`](docs/01_PRD.md) … [`docs/08_DEVELOPMENT_PLAN.md`](docs/08_DEVELOPMENT_PLAN.md) | Product, architecture, research, plan |
| [`progress.md`](progress.md) | Build log |

---

## Quickstart (local)

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+, Docker (for local Redis/SearXNG).

```bash
cp .env.example .env              # NIM key, Supabase DATABASE_URL etc. — docs/10_CONFIGURATION.md
cp web/.env.example web/.env.local
docker compose -f compose.dev.yml up -d valkey searxng
uv sync && uv run alembic upgrade head
uv run uvicorn deno_api.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker deno_worker.tasks:broker --workers 1
cd web && npm install && npm run dev   # http://localhost:3000
```

Without Supabase keys the app runs in dev mode (no login). Next.js proxies `/api/*` to `BACKEND_URL`.

## Tests

```bash
uv run ruff check . && uv run mypy && uv run pytest     # integration: docker compose -f compose.dev.yml --profile test up -d postgres-test
uv run pytest -m live                                   # live NIM tests (opt-in)
cd web && npm run lint && npx tsc --noEmit && npm run build
```

## Deploy

```bash
git push origin main            # web redeploys on Vercel automatically
bash deploy/deploy-free.sh      # backend: build image, update Cloud Run job + API + crons
```

Details, first-time setup and rollback: [`docs/09_FREE_DEPLOYMENT.md`](docs/09_FREE_DEPLOYMENT.md).
