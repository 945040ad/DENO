# Deno — Founder Go-To-Market Workspace

> **"Deno tells you if your idea is worth building — then gives you everything you need to get your first users, for free channels, in your own voice, without getting banned."**

---

## Overview

Deno is a hybrid-architecture founder workspace designed for 2026 platform reality. It addresses the two sequential walls every founder faces:
1. **Stage 1 (Validation — Free):** An 8-agent adversarial DAG that stress-tests a startup idea, bottom-up sizes the market (TAM/SAM/SOM), identifies competitors with clickable sources, and maps the exact target subreddits and social communities with live rules.
2. **Stage 2 (Distribution — $20/mo):** A 30-day voice-matched content engine that produces platform-safe posts, hooks, and video scripts. Every single post carries a **Ban Risk Score (0–100)** powered by Peter Yang's 18 anti-slop rules (`petergyang/no-ai-slop`) and Serge Bulaev's 2026 vocabulary density heuristics (`sergebulaev/linkedin-skills`).

**Non-negotiable design constraint:** Deno never posts, votes, or messages automatically. A human always reviews and presses send (copy & deep-link).

---

## Technology Stack

* **API Gateway & Web Host:** Deno 2 (TypeScript, `Deno.serve`, static asset streaming)
* **Core ML & Agent Engine:** Python 3.14 + FastAPI + Pydantic v2 + NumPy (Burrows' Delta stylometry)
* **LLM Model & Provider:** NVIDIA NIM (`meta/llama-3.2-11b-vision-instruct` via `https://integrate.api.nvidia.com/v1`)
* **Persistence:** hosted Supabase Postgres + pgvector (Alembic migrations, RLS). Free-tier deploy plan: `docs/09_FREE_DEPLOYMENT.md`
* **Frontend UI:** Vanilla CSS (editorial hard-edge design system — DM Serif Display / Schibsted Grotesk / JetBrains Mono) + Vanilla JS (Reactive DOM & SSE streaming)

---

## Directory Structure

```
├── .env                              # Environment configuration (NVIDIA NIM key, ports)
├── .env.example                      # Template environment variables
├── .gitignore                        # Git exclusion rules
├── README.md                         # Project documentation
├── docs/                             # Full architectural & research documentation
│   ├── 01_PRD.md                     # Product Requirements & User Stories (US-001 to US-014)
│   ├── 02_ARCHITECTURE.md            # Hybrid architecture, LangGraph DAG, schemas
│   ├── 03_ANTI_SLOP_TAXONOMY.md      # Peter Yang 18 patterns + 2026 density rules
│   ├── 04_STORY_BANK_AND_STYLOMETRY.md # Burrows' Delta math & Founder Story Bank
│   └── 05_PLATFORM_RULES_AND_COMMUNITIES.md # 30 target subreddits & platform limits
├── gateway/                          # Deno 2 API Gateway & Web Server
│   ├── server.ts                     # Reverse proxy to FastAPI & static file server (Port 8080)
│   └── server_test.ts                # Deno native test suite
├── backend/                          # Python Core Engine (Port 8000)
│   ├── app/
│   │   ├── config.py                 # Pydantic Settings & .env loading
│   │   ├── main.py                   # FastAPI app with REST & SSE endpoints
│   │   ├── models/schemas.py         # Strict Pydantic domain models
│   │   ├── db/storage.py             # Idempotent SQLite storage manager
│   │   ├── engine/
│   │   │   ├── anti_slop.py          # 18-pattern AST/regex detector (no-ai-slop)
│   │   │   ├── density_scorer.py     # 2026 AI Tell & paragraph density scorer
│   │   │   ├── stylometry.py         # Burrows' Delta distance & vector calculator
│   │   │   └── ban_risk.py           # Unified 0-100 Ban Risk Scorer with fixes
│   │   └── agents/
│   │       ├── llm_client.py         # Async NVIDIA NIM client
│   │       ├── validation_pipeline.py# 8-agent adversarial validation DAG
│   │       └── content_pipeline.py   # 30-day calendar planner with Story Bank
│   └── tests/                        # Pytest automated test suite
│       ├── test_anti_slop.py         # Tests for all 18 slop patterns
│       ├── test_density_scorer.py    # Tests for 2026 vocabulary density tells
│       ├── test_stylometry.py        # Tests for Burrows' Delta & voice distance
│       ├── test_ban_risk.py          # Tests for 0-100 score & deductions
│       ├── test_api.py               # Tests for FastAPI endpoints & storage
│       └── test_validation_live.py   # Live end-to-end multi-agent pipeline test
└── public/                           # Frontend Web Assets
    ├── index.html                    # Marketing landing page
    ├── auth.html                     # Log in / sign up
    ├── app.html                      # Founder workspace (6-tab product)
    ├── base.css                      # Shared design-system tokens & primitives
    ├── landing.css / landing.js      # Landing page styles & interactions
    ├── auth.css / auth.js            # Auth page styles & client-side validation
    ├── app.css / app.js              # Workspace styles & reactive UI / SSE listener
    └── assets/                       # Static images (e.g. workspace-intake.png)
```

---

## Quickstart

### 1. Prerequisites
- Python 3.10+ installed
- Deno 2+ installed
- NVIDIA NIM API Key configured in `.env`

### 2. Start the Backend (FastAPI - Port 8000)
```bash
# Activate virtual environment
source .venv/bin/activate

# Launch FastAPI server
uv run uvicorn deno_api.main:app --host 127.0.0.1 --port 8000
```

### 3. Start the web app (Next.js - Port 3000)
```bash
cd web
cp .env.example .env.local   # add the Supabase URL + publishable key (docs/supabase-setup.md)
npm install
npm run dev
```

Next.js serves the UI and proxies `/api/*` to FastAPI (`BACKEND_URL`, default `http://127.0.0.1:8000`).

### 4. Access Deno
Open `http://localhost:3000` for the landing page, `/auth` to log in or sign up, and `/app` for the founder workspace. Without Supabase keys the app runs in dev mode (no login required); with them, `/app` requires a session.

The legacy static client (`public/`) and Deno gateway (`gateway/`) still run as before on port 8080 until they're removed (docs/08 Phase 1b).

---

## Automated Test Suite

Run unit and integration tests across the stack:

```bash
# Run backend pytest suite (includes Supabase JWT + per-user isolation tests)
uv run pytest

# Web: lint, types, production build
cd web && npm run lint && npm run typecheck && npm run build

# Web: pixel-parity check against the original static pages
# (serve public/ on :8088 and `next start -p 3100` first)
cd web && npm run test:visual

# Run Deno gateway test
deno test --allow-net --allow-read gateway/server_test.ts

# Run end-to-end live pipeline test against NVIDIA NIM
uv run pytest -m live
```
