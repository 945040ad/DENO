# Deno — Flagship Rebuild & Launch Plan

**Date:** 2026-09-24
**Inputs:** a full backend audit; the cloned and read source of `sergebulaev/linkedin-skills`, `sergebulaev/x-skills` and `petergyang/no-ai-slop`; probes of every endpoint below from this machine; and research on the 2026 LangGraph/RAG stack and on competitors.

**Constraint:** no official platform API keys and no logged-in sessions or cookies.

---

## 1. Where the project really stands

Deno has a strong idea and a good UI. The intelligence behind it is mostly theatre. An audit of the code found:

| Claim in the README/PRD | Reality in the code |
|---|---|
| "Grounded evidence, verified URLs" | The LLM invents competitor URLs (`validation_pipeline.py:129`); fallbacks are hard-coded jasper.ai and census.gov (`:223-276`); the pain quotes are 3 fixed strings (`:282-286`) |
| "Community radar with live rules" | The same `SEED_COMMUNITIES` list comes back for every idea (`:17-88`, `:288`) |
| "8-agent LangGraph DAG" | A hand-rolled `asyncio.gather`; agent 6 doesn't exist; agent 4's output never reaches the report |
| "Calibrated confidence" | An LLM-made number that is never clamped; it can fail schema validation (`schemas.py:100`) |
| "Voice-matched, anti-slop generation" | The engines only **score after** generation; nothing regenerates. The 7-day topics are hard-coded. `HOOK_FORMULAS` is never used |
| "Burrows' Delta" | No corpus z-scores, and `max(val,1.0)` stands in for the standard deviation (`stylometry.py:85-98`) |
| "18 slop rules" | 16 are implemented; only the first match is reported |

**Robustness and security:**
- **Endpoints:** no auth on any of them.
- **CORS:** `*` together with credentials (`main.py:35-41`).
- **Leaked errors:** raw exception text is streamed to clients (`main.py:127`).
- **Blocking calls:** sync `sqlite3` runs in async handlers, and `/validate` blocks until the whole pipeline finishes.
- **SSE:** the stream loops forever on an unknown id.
- **Concurrency:** a shared progress callback means two runs at once cross-talk (`main.py:118`).
- **Tests:** they write to the real DB, and the live NIM test isn't marked or skipped.
- **Packaging:** there's no `requirements.txt` or `pyproject.toml`.
- **Secrets:** `.env` is handled correctly (gitignored and never committed).

**Keep as-is (pure, testable):**
- `engine/density_scorer.py`
- `engine/anti_slop.py`: keep the table-driven design, add the 2 missing patterns and report every match.
- `engine/ban_risk.py`: move the rules into data.
- `models/schemas.py`
- The editorial frontend
- The human-send-only principle, which is the product's moral centre.

**Rewrite:** `llm_client.py`, `validation_pipeline.py`, `content_pipeline.py`, `storage.py`, and the Delta maths in `stylometry.py`.

**The one thing that 10x's it** (from the product-lens review): make every sentence of the verdict traceable to a real public post. That turns Deno from "another AI idea validator" into the only one you can audit.

---

## 2. How `linkedin-skills` gets LinkedIn data, and what to copy

This comes from reading the repo's source, not its README marketing.

- **Read layer:** `lib/apify_client.py` calls **paid Apify actors labelled "no-cookies"**:
  - `apimaestro~linkedin-post-detail`
  - `…comments-replies…-no-cookies`
  - `scraping_solutions~…engagers…-no-cookies`

  These need an `APIFY_TOKEN` ($5/mo free credit). `x-skills` does the same for X with `xquik~x-tweet-scraper`.
- **Write layer:** Publora (`PUBLORA_API_KEY`). With no keys set, the tool falls back to drafts you copy and paste.
- **What it doesn't do:** log into LinkedIn, or contain a scraper of its own. The vendor scrapes LinkedIn's public guest pages.

**Copy the architecture, not the vendor:**
1. One thin client per source, all returning one flat `Post` contract.
2. An in-process LRU cache (6h TTL).
3. 3 retries with jittered backoff on 408, 429 and 5xx.
4. **Tier auto-detection** with graceful fallback:
   - Tier 0: keyless, our own scrapers (the default).
   - Tier 1: an optional `APIFY_TOKEN` using the same no-cookie actors.
   - Tier 2: manual paste.
5. Drafts only. A human presses send.

---

## 3. Keyless data layer: what actually works (probed 2026-09-24)

| Source | Endpoint / tool | Status | What we get |
|---|---|---|---|
| **Reddit** | Arctic Shift `…/api/posts/search` and `/comments/search` (`subreddit`/`author` + `query`/`title`/`body`, `after`/`before`, `fields`) | ✅ keyless, data minutes old | Full post/comment JSON with scores. **Needs a subreddit**; there's no search across all of Reddit. Honour `X-RateLimit-Reset` |
| Reddit | `/r/<sub>/new/.rss`, `/top/.rss` | ✅ | Fresh listings |
| Reddit | `search.rss` | ⚠️ intermittent 403 | Opportunistic only |
| Reddit | `.json` endpoints, PullPush | ❌ 403 / 429 | — |
| **X** | `cdn.syndication.twimg.com/tweet-result?id=` | ✅ | Full tweet JSON including `favorite_count`, for a **known ID** |
| X | `publish.twitter.com/oembed` | ✅ | Text fallback |
| X | Nitter/XCancel, timelines | ❌ dead (X legal action Aug–Sep 2026) | — |
| **LinkedIn** | `/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=` | ✅ 50 cards per call | **Hiring-demand signal**, low risk |
| LinkedIn | Public `/posts/…` pages through Scrapling/crawl4ai | ⚠️ expected to work logged-out (OG/JSON-LD); 999/authwall under load | Post text for a **known URL** |
| **Discovery** for X and LinkedIn | Self-hosted **SearXNG** (37.5k★, AGPL; JSON output on) → `site:x.com/*/status`, `site:linkedin.com/posts` | ⚠️ engines throttle under sustained load | Post URLs to hydrate |
| HN | `hn.algolia.com/api/v1/search` | ✅ | Tech-founder demand, points |
| Product Hunt | `/feed` | ✅ | Competitor launches |
| Google Trends | `trending/rss` | ✅ | Trend signal |
| Bluesky | `getAuthorFeed`, `getPostThread` | ✅ (search is ❌ 403) | Known accounts only |
| Threads | — | ❌ login shell | Skip |

**Fetch stack:**
- **Scrapling** (83k★, BSD-3) with a **Camoufox** backend for stealth fetches.
- **crawl4ai** (84k★, Apache-2) when we want LLM-ready markdown.
- Avoid nodriver/zendriver: AGPL, and maintenance has slowed.

**Honest limits:**
- Finding posts on X and LinkedIn is the weak link. SearXNG spreads load across engines but still gets throttled.
- That is exactly why the optional Apify tier exists.
- Run the Phase 0 spike before committing to anything.

**Legal/ToS risk:**
- **X and LinkedIn:** high for scraping. LinkedIn §8.2 bans it; hiQ lost on contract. X's embed and syndication surfaces are lower risk.
- **Reddit:** high for scraping. Arctic Shift and listing RSS are the lowest-risk routes.
- **HN, Product Hunt, Trends, Bluesky:** low.

**Mitigations:**
- Fetch per idea, on demand, never as a standing monitor (continuous monitoring is what killed GummySearch).
- Cache aggressively and rate-limit.
- Store only public text, the URL and a timestamp.
- Never harvest profiles.

---

## 4. Target architecture

```
backend/app/
  sources/                  # read layer (linkedin-skills pattern)
    base.py                 # SourceClient protocol, Post contract, LRU cache, retry, token-bucket limiter
    reddit.py               # Arctic Shift → listing RSS → search.rss (opportunistic)
    x.py                    # SearXNG discovery → syndication hydrate → oEmbed fallback
    linkedin.py             # SearXNG discovery → Scrapling public-page parse; jobs-guest demand
    hn.py  producthunt.py  trends.py  bluesky.py
    searx.py                # SearXNG JSON client (+ Camoufox fallback)
    apify.py                # optional Tier 1 (APIFY_TOKEN), same actors as linkedin-skills
    selector.py             # tier detection + per-source health
  rag/
    ingest.py               # normalise → dedupe (URL hash) → chunk → embed
    store.py                # sqlite-vec (single file, alongside the checkpointer)
    retrieve.py             # hybrid BM25 + vector → rerank
  graphs/                   # LangGraph 1.2.x, SqliteSaver checkpointer, thread_id = project_id
    validation.py
    content.py
    trends.py               # subgraph shared by both
  gates/                    # deterministic + judge gates used as graph nodes
    scrub.py  slop.py  density.py  voice.py  ban_risk.py  judge.py
  llm/
    models.py               # LangChain init_chat_model; per-node routing (see §7)
  engine/                   # kept pure functions (density, anti_slop, ban_risk, stylometry v2)
```

**Stack:**
- LangGraph **1.2.12** and LangChain **1.0**. Use `langchain.agents.create_agent`, not the deprecated `create_react_agent`.
- Embeddings: NVIDIA **llama-nemotron-embed-1b-v2**. Reranker: **llama-nemotron-rerank-1b-v2**. Local fallbacks are BGE-M3 and bge-reranker-v2-m3; confirm the hosted model IDs on build.nvidia.com.
- Vector store: **sqlite-vec**, so there's no new server.
- Evaluation: **Ragas** plus a custom citation checker.
- Traces: **Langfuse** cloud free tier (self-hosting it needs ClickHouse, Postgres, Redis and S3).

---

## 5. Validation graph (accuracy first)

Patterns borrowed from `open_deep_research` (the supervisor fans out researcher subgraphs that compress their findings with source IDs; that repo was archived in Aug 2026) and from STORM (multi-perspective questions and an outline built before writing).

```
intake → perspective_planner (STORM) → query_planner
       → Send() fan-out: reddit | x | linkedin_posts | linkedin_jobs | hn | producthunt | trends
       → ingest (RAG)
       → Send() fan-out of grounded analysts: pain | demand | competitors | ICP | willingness_to_pay | risks | communities
       → citation_validator   (drops any claim not entailed by its cited chunk)
       → signal_scorer        (deterministic numbers)
       → critic ↔ refiner     (max 2 rounds)
       → verdict              → interrupt() for founder review
```

- **Analysts may only cite chunk IDs.** URLs come from the store and never from the model.
- **Signals are computed, not generated:**
  - Mention volume and 90-day trend
  - An engagement-weighted pain score (score normalised against each subreddit's median)
  - Count of "I'd pay for / is there a tool that" phrases
  - Number of LinkedIn job postings
  - Competitor frequency, plus Product Hunt launches in the last 12 months
- **Confidence = f(evidence coverage, source diversity, signal agreement).** Below a threshold, the verdict is **"Insufficient evidence"**, with the gaps listed, and never a guess.
- **Communities** are ranked from where the pain posts actually appear. The rules (karma gate, promo policy) come from the curated rules file and the subreddit sidebar, so `SEED_COMMUNITIES` is no longer the answer for every idea.

---

## 6. Content graph: trend-aware and human

**Trend miner** (subgraph):
- Pull the top posts from the last 30 days in the idea's actual communities: Reddit through Arctic Shift, HN, X and LinkedIn through discovery + hydrate.
- Reuse patterns from `mvanhorn/last30days-skill` (62.7k★, MIT): engagement ranking plus cross-platform agreement. Keyless for Reddit, HN, GitHub and arXiv.
- Classify each post into the **F1–F20 hook formulas** (`linkedin-skills/references/hook-formulas.md`) with an LLM classifier ported from `linkedin-hook-extractor`.
- Rank formulas per topic by **engagement relative to the author's own median**, not raw likes.
- Treat the vendor-reported lift numbers (MagicPost, AuthoredUp) as priors only.

**Voice:**
- Few-shot from the founder's real posts (pasted in, or public URLs hydrated through the source layer).
- Stylometry v2 with a real Burrows' Delta: corpus z-scores and 150 most-frequent words.
- The Story Bank is the only allowed source of anecdotes and numbers. **Inventing claims is a hard fail.**

**Gate loop** (from the anti-slop research; none of these repos ships an importable library, so we build the gates ourselves):

| Layer | Implementation | Source |
|---|---|---|
| 1 Scrub (always on) | Regex: model leakage (`oaicite`, "As of my last update", `[Your Name]`), em-dash rate | linkedin-humanizer FORENSIC tier |
| 2 Hard-fail regex | Banned words (delve, leverage, tapestry…), reveal bridges ("The result?"), negative parallelism, sincerity openers, colon reveals, summary endings | no-ai-slop "cut" lists + humanizer STRICT |
| 3 Density | Per-paragraph `score_paragraph()`: 3+ hits → rewrite, 2 → swap | `linkedin-humanizer/references/scrub-rules.md` (copy almost verbatim) + existing `density_scorer.py` |
| 4 Post-level | ≤1 triad, ≤1 contrast, ≤2 fragments, rhythm variance, a specific (number or name) within 2 lines of every abstract claim | humanizer Pass 2/4, hook-formulas density rule |
| 5 LLM judge | The 20 pass/fail checks in no-ai-slop `eval.md` (portability test, invented claims, fake-profound endings) + an over-correction guard → JSON `{check_id, pass, quote, fix}` | no-ai-slop `eval.md` |
| + Voice | Delta distance below the founder's own spread | stylometry v2 |
| + Ban risk | Community rules from data, not hard-coded | `ban_risk.py` |

**Flow:**
1. Draft.
2. Run layers 1–4 (milliseconds). On failure, send **only the failing spans** to a rewrite.
3. Run layer 5.
4. At most 2 rewrites.
5. Re-run layers 1–4.
6. `interrupt()` for human approve/edit.
7. The founder copies the post and follows the deep link. **Never auto-post.**

**Optional extras:**
- `sam-paech/slop-score` (port its Node scorer) as an extra metric.
- The `antislop-sampler` phrase list as extra banned phrases.
- `tbhb/vale-ai-tells` if we want Vale.
- **Don't gate on AI-detector scores:** on 100–300-word posts they're noise.

---

## 7. LLM layer

- Use LangChain `init_chat_model`, so any provider is a config change.
- Keep **NVIDIA NIM** as the free default, but route per node:
  - **Cheap/fast** (Llama-3.2-11B or similar): classification, query expansion, hook labelling.
  - **Strong** (Llama-3.3-70B / Nemotron-class on NIM; Claude or another frontier model optional): analysts, critic, verdict, drafting, judge.
- Use structured output (`with_structured_output` + Pydantic) instead of regex JSON extraction.
- Per-node timeouts (LangGraph 1.2); shared async `httpx` client; retries.

---

## 8. Platform hardening (needed before any launch)

- **Auth:** magic-link or OAuth-less email login, and project ownership checks.
- **CORS** allow-list; remove raw error text from responses.
- **Async DB** (aiosqlite) or Postgres. Switch on foreign keys and add indexes and migrations.
- **Jobs:** validation runs as a background job keyed by `thread_id`. SSE streams LangGraph `astream` events with heartbeats and disconnect handling. Delete the global `project_progress` dict.
- **Rate limiting** per user, since LLM and scrape calls cost money.
- **Packaging:** `pyproject.toml` (uv); Docker Compose with app, SearXNG and Valkey.
- **Tests:** fixture-recorded source tests (no network in CI); `@pytest.mark.live` for live tests; a temp DB.

---

## 9. Build order

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 Spike** (2 days) | SearXNG in Compose; discovery hit-rate for `site:x.com` and `site:linkedin.com/posts` over 10 test ideas; LinkedIn public-post parse with Scrapling | ≥60% of ideas yield ≥10 hydrated X/LI posts → go keyless; otherwise enable the Apify tier |
| **1 Foundations** | pyproject/uv, Compose, auth, CORS, async DB, job runner, LangChain model router | Existing 21 tests green, no blocking I/O |
| **2 Sources** | `sources/*` with cache, retry, tier selector; `scripts/probe_sources.py` | Fixture tests for every client; live probe report |
| **3 RAG** | ingest, sqlite-vec, hybrid retrieval + rerank | Recall@10 ≥ 0.8 on a 20-idea labelled set |
| **4 Validation graph** | §5 end to end; delete every hard-coded or LLM-made URL | 0 unsupported URLs; citation precision ≥ 0.9 (Ragas faithfulness + checker) |
| **5 Content graph** | Trend miner, voice v2, 5-layer gate loop, interrupt | ≥90% of drafts pass the gates in ≤2 rewrites; blind human A/B beats the current output |
| **6 UI** | Evidence explorer (every claim → the real post), trend feed, gate diff view ("what the gate flagged → fix") | Every claim links to a real, clickable post |
| **7 Evals & observability** | Ragas + eval set in CI, Langfuse traces, cost per run | Regression gate in CI |

---

## 10. Launch plan

**Positioning:** *Deno tells you whether to build it, with every claim linked to a real post. Then it writes your first 30 days of Reddit, X and LinkedIn posts in your own voice, checked against what gets founders banned.*

**Differentiators vs competitors:**
1. **Sourced verdict → distribution.** ValidatorAI and DimeADozen ($9–$179 one-time) stop at a report.
2. **Ban-risk and anti-slop gating.** Taplio ($39–199/mo), Supergrow ($19–139) and AuthoredUp ($20–45) write or format posts but don't score them against community rules.
3. **Per-idea, on-demand data.** No standing monitor, which is the pattern that made GummySearch unviable (shut down Nov 2025 over Reddit API pricing). That makes it cheaper and more defensible.

**ICP:** solo or two-person pre-seed technical founders at zero revenue who build in public and won't pay $199/mo tool stacks.

**Communities:** r/SideProject, r/microSaaS and r/indiehackers, plus Show HN and Product Hunt. Follow each one's karma and cadence rules in `05_PLATFORM_RULES_AND_COMMUNITIES.md`.

**Six-week timeline:**
- **Weeks 1–2, pre-launch:**
  - Waitlist on the existing landing page.
  - Build in public: X daily, LinkedIn 2–3 times a week (≤1,300 characters, link in the first comment).
  - Open-source the gate library in week 2 so stars start accumulating.
- **Week 3, launch:**
  - Mon: r/SideProject, a story-led post.
  - Tue, ~7am PT: Show HN, "I made a validator that links every claim to a real Reddit/HN/X post".
  - Wed: Product Hunt.
  - Thu: r/microSaaS, with real waitlist metrics.
  - Fri: the r/indiehackers weekly thread.
  - Mirror each day's milestone on X and LinkedIn that evening, not at the same moment.
- **Weeks 4–6:**
  - A weekly public teardown of a real startup idea run through Deno.
  - One open-source release a week.
  - Push free→$20/mo once 100 or more verdicts exist.

**Dogfood:**
- Run Deno through its own Stage 1 and publish the unedited verdict, confidence and source ledger, whatever they say.
- Run Stage 2 on it and publish the before/after gate diffs ("first draft failed 7 checks; here's what changed").
- This is also the proof that the gates work.

**Open-source (MIT), to earn stars:**
- `deno-slop-gate`: the 5-layer gate, crediting no-ai-slop and linkedin-humanizer.
- `deno-sources`: the keyless source clients and citation-ledger schema.
- The Delta/ban-risk scorers.

**Stays paid:** the orchestrated graphs and prompts, the calendar planner, the Story Bank/voice capture, and the hosted app.

**Metrics:**
- **Pre-launch:** waitlist ≥300, impressions, stars.
- **Launch:** HN points, PH rank, Reddit posts not removed, idea→verdict activation.
- **Post-launch:** free→paid conversion, D7/D30 retention, gate pass rate, draft→final edit distance, and brand mentions tracked with F5Bot.

**Unverified claims to avoid in launch copy:**
- LinkedIn's "slop-report button" view penalties.
- Reddit's LLM spam classifier.
- Hook-formula lift percentages.

All three come from vendors or third parties, so don't quote them as fact.

---

## 11. Agents and skills to use during the build

| Step | Tool |
|---|---|
| Planning each phase | `ecc:plan`, `ecc:architect`, `ecc:blueprint` |
| TDD per module | `ecc:tdd-workflow`, `ecc:tdd-guide` |
| Source clients | `ecc:data-scraper-agent`, `ecc:api-connector-builder` |
| RAG review | `ecc:rag-pipeline-reviewer`, `ecc:eval-harness` |
| LangGraph/FastAPI review | `ecc:fastapi-reviewer`, `ecc:python-reviewer`, `ecc:silent-failure-hunter` |
| Security before launch | `ecc:security-reviewer`, `/security-review` |
| Content gates | `no-ai-slop` skill (rules + eval), `ecc:brand-voice`, `ecc:content-engine` |
| Launch execution | `ecc:marketing-agent`, `ecc:crosspost`, `ecc:seo-specialist` |
| UI | `ecc:frontend-design-direction`, `ecc:a11y-architect`, `ecc:e2e-runner` |
