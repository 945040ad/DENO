# Phase 0 — Feasibility spike report

**Date:** 2026-09-24 · **Scripts:** `spikes/nim_model_bench.py`, `spikes/discovery_probe.py` · **Raw data:** `docs/spikes/nim_models.json`, `docs/spikes/discovery_probe.json`

## 1. Verdict

| Question (PRD Milestone 0) | Answer |
|---|---|
| Can we find ≥10 real X/LinkedIn posts for ≥60% of ideas without keys? | **Yes — 8/10 ideas (80%).** Keyless only; the Apify tier is **not** needed for MVP. |
| X hydration without keys? | **98%** via `cdn.syndication.twimg.com` (oEmbed fallback never needed). |
| LinkedIn public post pages logged-out? | **100%** (10/10 per idea, HTTP 200, 0 authwall/999) at 1 request / 2.5 s. |
| NIM embeddings / rerank available? | Embeddings **yes** (`nvidia/nemotron-3-embed-1b`, 2048-d). Rerank **yes** (`nvidia/llama-nemotron-rerank-vl-1b-v2`); every other reranker is end-of-life or not deployed. |
| A model fast and good enough under the 40 req/min cap? | **`nvidia/nemotron-3-super-120b-a12b`** — ~1.2 s to first token, ~3.5 s for a 500-char answer, structured output works. |

## 2. LLM benchmark (NIM, via LangChain `ChatNVIDIA` / `ChatOpenAI`)

Short analyst prompt (≤400 tokens) + `with_structured_output(Claims)`. Shared limiter at 36 req/min. Latency is queue-dependent — re-run `spikes/nim_model_bench.py` before changing routing.

| Model | TTFT | Total | Structured output | Notes |
|---|---|---|---|---|
| **nvidia/nemotron-3-super-120b-a12b** | 1.1–1.3 s | 3.4–3.6 s | ✅ guided_json 6.3 s · json_schema 5.5 s · json_mode 4.2 s | **Chosen for every role** |
| meta/llama-3.2-11b-vision-instruct | 0.3–11 s | 19–37 s | ✅ json_mode only (15 s) | Fallback |
| z-ai/glm-5.3-flash | 66 s | 71 s | ✅ (38 s) | Too slow (queue) |
| nvidia/nemotron-3.5-lightning-30b-a3b | 3.6–57 s | — | ❌ (rejects guided_json; length errors) | Unstable queue |
| z-ai/glm-5.3 | 7–9 s | — | ❌ reasoning exhausts tokens | — |
| deepseek-ai/deepseek-v4.1-flash | 16–20 s | — | ❌ | — |
| openai/gpt-oss-20b, moonshotai/kimi-k3, google/gemma-4-31b-it | timeout (>60 s) | | | Queue |
| kimi-k2.6, gemma-3-12b, mistral-nemo-12b, mistral-large-2, nemotron-ultra-253b, nemotron-nano-3 | 404 | | | Listed but not deployed for this key |

Function-calling structured output fails on every model tested through the OpenAI-compatible endpoint (tool call not returned) → the router uses **`json_schema`** (or NIM `guided_json` via `ChatNVIDIA`), never `function_calling`.

## 3. Keyless discovery (10 ideas)

| Idea | X found / hydrated | LI posts found / hydrated | Reddit comments (2 subs) | HN hits | LI jobs p1 |
|---|---|---|---|---|---|
| linkedin ghostwriter | 19 / 10 | 31 / 10 | 25 | 15 | 20 |
| customer churn | 22 / 9 | 40 / 10 | 25 | 5604 | 20 |
| cold email deliverability | 3 / 3 | 32 / 10 | 25 | 204 | 20 |
| invoice reminders | 4 / 4 | 21 / 10 | 0 | 706 | 20 |
| meal prep app | 2 / 2 | 22 / 10 | 25 | 3631 | 20 |
| flaky tests | 33 / 10 | 38 / 10 | 0 | 1945 | 20 |
| rent tracking | 3 / 3 | 40 / 10 | 25 | 8792 | 20 |
| podcast editing | 9 / 9 | 20 / 10 | 50 | 1073 | 20 |
| remote team onboarding | 0 / 0 | 3 / 3 | 0 | 562 | 20 |
| Shopify returns | 0 / 0 | 0 / 0 | 50 | 373 | 20 |

Discovery: SearXNG (Docker, JSON output) — Google/Brave/Bing via SearXNG honour `site:`; direct Bing RSS ignores `site:` and DuckDuckGo HTML returns a CAPTCHA. Hydration p50: 731 ms.

**Observations that shape Phase 5:**
- X is the thinnest source for niche/consumer ideas → the query planner must generate several phrasings per idea (the probe used one exact phrase).
- The last two ideas ran after ~40 SearXNG queries; engine throttling is likely → rotate engines, cache 24 h, cap per-run queries.
- Arctic Shift: `comments/search?body=` works (~7 s); `posts/search?query=` (full text) times out — use `title=` for posts.
- Reddit's own `search.json` returns 403 to bots; `/.rss` listings work.
- LinkedIn guest jobs: `seeMoreJobPostings` (not `seeAMore…`) with a browser UA; 20 cards/page.

## 4. Decisions (ADRs finalised)

- **ADR-007 Embeddings / rerank:** `nvidia/nemotron-3-embed-1b` (2048-d, fixed — no Matryoshka truncation) stored as pgvector **`halfvec(2048)`** (HNSW limit on `vector` is 2000 dims); rerank with `nvidia/llama-nemotron-rerank-vl-1b-v2`.
- **ADR-008 LLM routing:** roles `fast`, `strong`, `judge` all → `nvidia/nemotron-3-super-120b-a12b`, structured output via `json_schema`; fallback `meta/llama-3.2-11b-vision-instruct` (`json_mode`). Global client-side limiter ≤36 req/min per key, per-call timeout 60 s, one retry on 429/5xx.
- **ADR-009 Social data:** keyless tiers confirmed. Apify stays an optional, disabled-by-default tier.
