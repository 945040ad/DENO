# Deno Flagship — Evidence-Grounded Validation & Human-Voice Distribution

## Problem
Pre-seed technical founders waste weeks building ideas nobody wants. When they do launch, their posts either sound like AI or break community rules and get removed.

Today's validators produce reports that read well but cite nothing checkable. Today's content tools produce generic, detectable text with no awareness of community rules.

Deno v1 has the same flaw: every "source" in its verdict is invented by the model or hard-coded (see `docs/07_FLAGSHIP_REBUILD_AND_LAUNCH.md` §1). Leaving this unsolved means the product's core promise, a verdict you can trust, is false.

## Evidence
- **Code audit (2026-09-24):**
  - Competitor URLs are LLM-invented.
  - Pain quotes are 3 fixed strings.
  - Communities are identical for every idea.
  - Confidence is an unclamped LLM number.
  - Anti-slop gates never trigger a rewrite.
- **Market:**
  - GummySearch (Reddit audience research) shut down in Nov 2025 when API costs made continuous monitoring unviable, which shows demand existed.
  - ValidatorAI and DimeADozen sell uncheckable reports at $9–$179.
  - Taplio, Supergrow and AuthoredUp charge $19–$199/mo for LinkedIn writing with no ban-risk scoring.
- **Founder pain, demand for the combined workflow, and willingness to pay $20/mo:** Assumption — needs validation via 15 founder interviews plus waitlist conversion.

## Users
- **Primary:** solo or two-person, pre-seed, technical founders at zero revenue. They are deciding whether to commit the next 1–3 months to an idea, and they plan to get their first users through Reddit, X, LinkedIn and HN without paid ads.
  - **Trigger:** "I have an idea; is it real, and where do I find the first 100 users?"
- **Secondary:** indie hackers building in public who need a steady supply of platform-safe posts in their own voice.
- **Not for:**
  - Agencies running many client accounts.
  - Growth teams wanting auto-posting, DM automation or engagement pods.
  - Anyone wanting bulk lead scraping or profile harvesting.
  - Enterprises needing SSO or SOC 2 (deferred).

## Hypothesis
We believe **a validation verdict where every claim links to a real public post, followed by a trend-aware content plan gated for AI-tells and community rules**, will **let founders decide faster and launch without bans or slop** for **pre-seed technical founders**.

We'll know we're right when:
- ≥40% of activated users generate a content plan after their verdict.
- ≥5% convert to paid within 30 days.
- Sampled audits show ≥90% of verdict claims supported by their cited source.

## Success Metrics
| Metric | Target | How measured |
|---|---|---|
| Citation precision (claim supported by cited post) | ≥ 0.90 | Automated checker + weekly manual audit of 20 runs |
| Fabricated source URLs | 0 | Any URL in output not present in the retrieved store = failure |
| "Insufficient evidence" correctly returned on junk ideas | ≥ 90% | Labelled eval set of deliberately empty/nonsense ideas |
| Validation run time (p95) | ≤ 4 min | Job telemetry |
| Draft gate pass within ≤2 rewrites | ≥ 90% | Gate telemetry |
| Human edit distance draft→approved | trending down; baseline TBD | Diff of approved vs generated |
| Blind human preference vs v1 output | ≥ 70% prefer new | 30-sample blind A/B |
| Activation (signup → first verdict) | ≥ 60% | Product analytics |
| Verdict → content plan | ≥ 40% | Product analytics |
| Free → paid (30 days) | ≥ 5% | Billing |
| D30 retention (paid) | ≥ 60% | Billing / analytics |
| API availability | 99.5% monthly | Uptime monitor |
| Posts removed by moderators (user-reported) | < 5% | In-app feedback |

## Scope
**MVP:**
- An authenticated user submits an idea.
- Deno collects real public evidence from Reddit, X, LinkedIn (posts and job listings), HN and Product Hunt, without platform keys or logins.
- It returns a Build / Pivot / Kill / Insufficient-evidence verdict. Every claim is clickable to its source, and the key signals (demand, pain, competition, hiring) are computed from the data.
- The user can then generate a 7-day content plan in their own voice, built from currently high-performing hooks in the communities where their audience is. Each draft passes the anti-slop, voice and ban-risk gates, and the user approves every post before copying it out.
- Paid tier unlocks 30-day plans and more runs.

**Out of scope:**
- Auto-posting, auto-commenting, DMs or voting — a core principle, never built.
- Logged-in or cookie-based scraping, and official platform API keys — a user constraint and ToS risk.
- Continuous social monitoring and alerts — the pattern that made GummySearch uneconomic; revisit after PMF.
- Image, carousel and video generation (v1 US-012) — deferred to post-MVP.
- Post-performance tracking (v1 US-014) — deferred; needs a user-supplied metrics import.
- Teams, agencies, SSO — deferred.
- Threads/Instagram/TikTok sources — no reliable keyless access.
- Native mobile apps.

## Delivery Milestones
| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 0 | Keyless data feasibility proven | Documented hit-rate: can we find ≥10 real X/LinkedIn posts for ≥60% of test ideas without keys? Decides whether the optional paid-scraper tier is needed | **done — 80%, keyless only** | docs/spikes/phase0.md |
| 1 | Secure multi-user foundation | Users can sign up, log in and see only their own projects (hosted Supabase Auth); the current UI runs pixel-identical in Next.js; the app runs as a deployable production stack | in progress | docs/08 Phases 1, 1b, 2, 3 |
| 2 | Real evidence collection | For any idea, Deno gathers and stores real public posts from every source, with links and timestamps | pending | docs/08 Phases 4–6 |
| 3 | Grounded verdict | Verdict where every claim links to a real post and signals are computed; fabricated URLs are impossible | pending | docs/08 Phases 7–8 |
| 4 | Human-voice content | 7-day plan from trending hooks, in the user's voice, all drafts passing gates, human approval required | pending | docs/08 Phases 9–10 |
| 5 | Product experience | Evidence explorer, trend feed, gate diff view; accessible and responsive | pending | docs/08 Phase 11 |
| 6 | Paid tier | Stripe subscription, quotas and usage limits enforced | pending | docs/08 Phase 12 |
| 7 | Launch-ready | Observability, security review, load test, backups, evals in CI, legal pages | pending | docs/08 Phases 13–14 |

## Open Questions
- [x] Does SearXNG discovery find enough X and LinkedIn posts, or is the paid-scraper tier required? → enough from a residential IP (80%); re-check from the VPS IP at deploy.
- [x] Can public LinkedIn post pages be parsed logged-out without 999/authwall? → yes, 100% at 1 req/2.5 s (low volume).
- [x] NVIDIA-hosted embedding and rerank available? → yes: nemotron-3-embed-1b + llama-nemotron-rerank-vl-1b-v2.
- [ ] Which model is strong enough for analyst, critic and judge nodes at acceptable cost: NIM 70B-class vs a frontier API?
- [ ] Pricing: is $20/mo right, and should validation be free-unlimited or free-metered? — needs validation via waitlist pricing test.
- [ ] Should the voice be learned from pasted samples only, or from public post URLs too (a ToS consideration)?
- [ ] Is legal review needed before storing scraped public post text (retention period, takedown process)?
- [ ] Hosting region and data residency (EU users → GDPR obligations).

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Keyless endpoints break or get blocked | High | High | Tiered fallbacks, per-source health checks, optional paid-scraper tier, graceful "partial evidence" results |
| Platform ToS / legal action (X, LinkedIn, Reddit) | Medium | High | On-demand per-idea fetch only, low volume, caching, store only public text + URL, takedown process, no profile harvesting |
| LLM hallucinated claims slip past validation | Medium | High | Chunk-ID-only citations, entailment check, fabricated-URL = hard failure, eval gate in CI |
| Search engines throttle SearXNG | High | Medium | Multi-engine rotation, caching, rate limits, Apify tier |
| LLM cost/latency too high on free tier | Medium | Medium | Per-node model routing, caching, quotas, cost telemetry |
| Anti-slop gates over-correct into bland text | Medium | Medium | Over-correction judge check, voice-distance gate, blind A/B evaluation |
| Prompt injection via scraped content | Medium | High | Treat all scraped text as untrusted data, delimiters, no tool access from analyst nodes, output schema validation |
| Solo-developer bandwidth | High | Medium | Strict milestone order; open-source components to attract contributors |

---
*Status: DRAFT — requirements only. Implementation plan: `docs/08_DEVELOPMENT_PLAN.md`.*
