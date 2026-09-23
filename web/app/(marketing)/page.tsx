import type { CSSProperties } from 'react';
import { DeepDive } from '@/components/landing/DeepDive';
import { Faq } from '@/components/landing/Faq';
import { ScrollReveal } from '@/components/landing/ScrollReveal';
import { SiteHeader } from '@/components/landing/SiteHeader';

const wallTitle: CSSProperties = { fontSize: 'clamp(26px,2.6vw,34px)' };
const inkTag: CSSProperties = { background: 'var(--ink)', color: 'var(--paper)' };

export default function LandingPage() {
  return (
    <>
      <SiteHeader />

      <section className="announce">
        <a href="#risk" className="announce__pill">
          <span className="tag tag--green" style={{ background: 'var(--green)', color: '#fff', borderColor: 'var(--green)' }}>New</span>
          <span className="announce__text">Ban Risk now covers the 2026 LinkedIn slop filter.</span>
          <span className="announce__cta">See what changed →</span>
        </a>
      </section>

      <section className="hero">
        <h1 className="display hero__title">Know if it&apos;s worth building.<br />Then go get your first 100 users.</h1>
        <p className="prose hero__sub">Eight adversarial agents stress-test your idea against real sources. Then Deno writes thirty days of posts in your own voice — every one scored for ban risk before you press send.</p>
        <div className="hero__actions">
          <a href="/auth?mode=signup" className="btn btn--lime btn--lg btn--raised">Validate an idea — free</a>
          <a href="#receipts" className="btn btn--ghost btn--lg">Read a sample verdict</a>
        </div>
        <p className="mono-plain hero__note">NO CARD · NO AUTO-POSTING · EVER</p>
      </section>

      <section className="hero-strip-wrap">
        <div className="hero-strip slab">
          <div className="hero-strip__grid">

            <div className="hero-strip__card">
              <div className="hero-strip__card-head">
                <span className="mono" style={{ color: 'var(--muted)' }}>Agent DAG · Live</span>
                <span className="pulse-dot"></span>
              </div>
              <div className="display" style={{ fontSize: 'clamp(30px,3.4vw,44px)' }}>BUILD</div>
              <div className="hero-strip__confidence">
                <span className="display" style={{ fontSize: 30, color: 'var(--green)' }}>84%</span>
                <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>calibrated confidence</span>
              </div>
              <div className="hero-strip__agents">
                <div><span style={{ color: 'var(--green)' }}>✓</span> Market Researcher</div>
                <div><span style={{ color: 'var(--green)' }}>✓</span> Sizing Engine</div>
                <div><span style={{ color: 'var(--green)' }}>✓</span> Critic (adversarial)</div>
                <div style={{ color: 'var(--muted)' }}><span>⟳</span> Community Mapper</div>
                <div className="hero-strip__bar"><span style={{ width: '76%' }}></span></div>
              </div>
            </div>

            <div className="hero-strip__card hero-strip__card--lime">
              <span className="mono">Day 06 · r/SideProject</span>
              <div className="display" style={{ fontSize: 'clamp(22px,2.2vw,28px)', margin: '12px 0' }}>I spent $14,000 building a feature nobody used. Here&apos;s the teardown.</div>
              <div style={{ fontSize: 13, lineHeight: 1.5 }}>Pulled from your Story Bank · 1 metric, 1 scar, 0 outbound links.</div>
              <div className="hero-strip__score">
                <span className="mono" style={{ color: 'var(--on-dark)' }}>Ban Risk</span>
                <span className="display" style={{ fontSize: 26, color: 'var(--lime)' }}>91</span>
              </div>
            </div>

            <div className="hero-strip__card hero-strip__card--art grid-wash grid-wash--blue">
              <div className="hero-strip__art-tag">u/yourhandle · 1.2k karma</div>
            </div>

            <div className="hero-strip__card hero-strip__card--peach">
              <span className="mono">Slop scrub · 18 rules</span>
              <div className="hero-strip__scrub">
                <div><span className="hero-strip__strike">In today&apos;s fast-paced world</span> −6</div>
                <div><span className="hero-strip__strike">It&apos;s not just X — it&apos;s Y</span> −9</div>
                <div><span className="hero-strip__strike">Let&apos;s dive in 🚀</span> −11</div>
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 'auto' }}>Every deduction ships with the rewrite that fixes it.</div>
            </div>

          </div>
        </div>
      </section>

      <section id="how" className="walls">
        <span className="tag tag--peach">The two walls</span>
        <h2 className="display walls__title">Building got cheap. Being believed got expensive.</h2>
        <p className="prose walls__sub">Every unfunded founder hits the same two walls in the same order. Deno is built as two stages, in that order — and the first one costs nothing.</p>

        <div className="walls__grid">
          <div className="wall-card" style={{ background: 'var(--green-soft)' }}>
            <div className="wall-card__head">
              <span className="display" style={wallTitle}>Stage 1 — Validation</span>
              <span className="tag tag--ink">Free</span>
            </div>
            <div className="wall-card__art grid-wash grid-wash--green">
              <div className="wall-card__block-a"></div>
              <div className="wall-card__block-b"></div>
              <div className="wall-card__block-c"></div>
              <span className="mono-plain" style={{ position: 'absolute', right: 28, bottom: 22, color: 'var(--green)' }}>TAM / SAM / SOM</span>
            </div>
            <div className="wall-card__body">
              <p className="prose" style={{ color: 'var(--ink-2)' }}>Paste the idea or a URL. Intake, Market, Sizing and Risk run concurrently, a Critic agent attacks the result, and a bounded refiner loop settles it. Nothing without a clickable source survives.</p>
              <a href="/app" className="link-mono">Run the DAG →</a>
            </div>
          </div>

          <div className="wall-card" style={{ background: 'var(--peach)' }}>
            <div className="wall-card__head">
              <span className="display" style={wallTitle}>Stage 2 — Distribution</span>
              <span className="tag tag--ink" style={inkTag}>$20/mo</span>
            </div>
            <div className="wall-card__art grid-wash grid-wash--peach">
              <div className="wall-card__bar-1"></div>
              <div className="wall-card__bar-2"></div>
              <div className="wall-card__bar-3"></div>
              <div className="wall-card__dot"></div>
            </div>
            <div className="wall-card__body">
              <p className="prose" style={{ color: '#3A2A22' }}>A thirty-day calendar with irregular cadence, a 9:1 value-to-promo ratio, and archetypes each community actually tolerates. Written against your stylometric fingerprint, not a house voice.</p>
              <a href="/app" className="link-mono">See the calendar →</a>
            </div>
          </div>

          <div className="wall-card" style={{ background: 'var(--blue-soft)' }}>
            <div className="wall-card__head">
              <span className="display" style={wallTitle}>The guardrail</span>
              <span className="tag tag--ink" style={inkTag}>0–100</span>
            </div>
            <div className="wall-card__art grid-wash grid-wash--blue">
              <div className="wall-card__score-box">
                <span className="display" style={{ fontSize: 58 }}>88</span>
                <span className="mono-plain" style={{ textAlign: 'center', color: 'var(--blue)' }}>SAFE<br />TO<br />SEND</span>
              </div>
            </div>
            <div className="wall-card__body">
              <p className="prose" style={{ color: '#1E2A38' }}>Eighteen structural slop patterns, 2026 vocabulary density tells, and live community rule conflicts — itemised as deductions with fixes, before your account is on the line.</p>
              <a href="#risk" className="link-mono">Open the Studio →</a>
            </div>
          </div>
        </div>
      </section>

      <section className="deepdive">
        <DeepDive />
      </section>

      <section id="risk" className="riskband">
        <div className="riskband__inner slab">
          <div className="riskband__grid">
            <div>
              <span className="tag tag--lime">Ban Risk Studio</span>
              <h2 className="display riskband__title">Reddit blocks ~25,000 spam posts a day. Don&apos;t be one.</h2>
              <p className="prose riskband__sub" style={{ color: 'var(--on-dark-soft)' }}>Paste any draft — ours or yours. The scrubber runs eighteen structural slop patterns, the density scorer checks 2026 vocabulary tells, and the rule engine checks the community you&apos;re aiming at. You get one number and a fix list.</p>
              <div className="riskband__actions">
                <a href="/app" className="btn btn--lime">Score a draft free</a>
                <a href="#receipts" className="btn" style={{ color: 'var(--on-dark)', borderColor: 'rgba(250,248,243,.4)' }}>See all 18 patterns</a>
              </div>
            </div>

            <div className="risk-card">
              <div className="risk-card__top">
                <div className="risk-card__score">
                  <span className="display" style={{ fontSize: 'clamp(46px,6vw,72px)' }}>88</span>
                  <span className="mono-plain" style={{ textAlign: 'center', color: 'var(--ink)' }}>Ban Risk<br />Score</span>
                </div>
                <div className="risk-card__meta">
                  <span className="mono-plain">Target · r/SaaS · LLM spam filter: strict</span>
                  <span style={{ fontSize: 14.5, fontWeight: 600, lineHeight: 1.4 }}>Clears the filter. Send as written.</span>
                </div>
              </div>
              <div className="risk-card__deductions">
                <div className="mono-plain" style={{ marginBottom: 10 }}>Itemised deductions</div>
                <div className="risk-card__item" style={{ background: 'var(--peach)' }}><span className="risk-card__pt" style={{ color: 'var(--red-ink)' }}>−11</span><span>Rule of three cadence ×4 · <span style={{ color: 'var(--muted)' }}>break two of the triads into single clauses</span></span></div>
                <div className="risk-card__item" style={{ background: 'var(--peach)' }}><span className="risk-card__pt" style={{ color: 'var(--red-ink)' }}>−7</span><span>Em-dash density 4.1/100w · <span style={{ color: 'var(--muted)' }}>2026 tell, cap at 1.5</span></span></div>
                <div className="risk-card__item" style={{ background: 'var(--amber-soft)' }}><span className="risk-card__pt" style={{ color: 'var(--amber)' }}>−4</span><span>Outbound link in body · <span style={{ color: 'var(--muted)' }}>move to first comment</span></span></div>
                <div className="risk-card__item" style={{ background: 'var(--green-soft)' }}><span className="risk-card__pt" style={{ color: 'var(--green)' }}>PASS</span><span>Voice distance 0.31 · <span style={{ color: 'var(--muted)' }}>within your fingerprint</span></span></div>
              </div>
              <div className="risk-card__foot">
                <span className="mono-plain">🔒 Human-send only</span>
                <div style={{ display: 'flex', gap: 8 }}>
                  <span className="btn btn--ghost btn--sm" style={{ pointerEvents: 'none' }}>Copy post</span>
                  <span className="btn btn--ink btn--sm" style={{ pointerEvents: 'none' }}>Open Reddit ↗</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="receipts" className="receipts">
        <span className="tag tag--amber">Receipts, not logos</span>
        <h2 className="display receipts__title">We have no customer logos yet. Here&apos;s what we do have.</h2>
        <p className="prose receipts__sub">Putting fake enterprise badges on a pre-launch page is exactly the behaviour Deno scores you down for. So: the real numbers, and a space for the first honest testimonial.</p>

        <div className="receipts__stats">
          <div className="receipt-stat" style={{ background: 'var(--green-soft)' }}><span className="display">8</span><span>agents in the adversarial validation DAG, one of them hostile by design</span></div>
          <div className="receipt-stat" style={{ background: 'var(--peach)', color: '#3A2A22' }}><span className="display">18</span><span>structural slop patterns detected and rewritten, not just flagged</span></div>
          <div className="receipt-stat" style={{ background: 'var(--blue-soft)', color: '#1E2A38' }}><span className="display">30</span><span>communities mapped with live rules, karma gates and promo ratios</span></div>
          <div className="receipt-stat" style={{ background: 'var(--lime)' }}><span className="display">0</span><span>posts, votes or DMs sent automatically. A human always presses send.</span></div>
        </div>

        <div className="receipts__cards">
          <div className="receipt-slot">
            <span className="mono-plain">Testimonial slot 01</span>
            <span className="display" style={{ fontSize: 22, lineHeight: 1.2, color: 'var(--muted)' }}>Reserved for the first founder who ships with Deno.</span>
            <span style={{ fontSize: 13, color: 'var(--muted)', marginTop: 'auto' }}>Beta cohort opens with 25 seats.</span>
          </div>
          <div className="receipt-note panel">
            <span className="mono-plain">Built in public</span>
            <span style={{ fontSize: 15, lineHeight: 1.55, color: 'var(--ink-2)' }}>Every verdict Deno produces is auditable: unit tests across the scoring engines, and a source ledger with retrieval timestamps on every claim.</span>
            <a href="docs/06_PROGRESS.md" className="link-mono" style={{ marginTop: 'auto' }}>Read the changelog →</a>
          </div>
        </div>
      </section>

      <section id="pricing" className="pricing">
        <div className="pricing__head">
          <span className="tag tag--blue">Pricing</span>
          <h2 className="display pricing__title">Validation is free. Forever.</h2>
        </div>
        <div className="pricing__grid">
          <div className="price-card">
            <span className="mono">Stage 1</span>
            <span className="display" style={{ fontSize: 52 }}>$0</span>
            <div className="price-card__list">
              <span>8-agent validation, unlimited ideas</span>
              <span>Build / Pivot / Kill with confidence</span>
              <span>Bottom-up TAM / SAM / SOM</span>
              <span>Source ledger with timestamps</span>
              <span>Community radar, 30+ mapped</span>
            </div>
            <a href="/auth?mode=signup" className="btn" style={{ marginTop: 'auto' }}>Start validating</a>
          </div>
          <div className="price-card price-card--featured">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span className="mono">Stage 2</span>
              <span className="tag tag--ink">25 beta seats</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="display" style={{ fontSize: 52 }}>$20</span>
              <span style={{ fontSize: 14, fontWeight: 600 }}>/month</span>
            </div>
            <div className="price-card__list">
              <span>Everything in Stage 1</span>
              <span>30-day voice-matched calendar</span>
              <span>Ban Risk Score on every draft</span>
              <span>Anti-slop scrubber + rewrites</span>
              <span>Story Bank &amp; stylometric fingerprint</span>
              <span>Hook library, video scripts, reply drafts</span>
            </div>
            <a href="/auth?mode=signup" className="btn btn--ink" style={{ marginTop: 'auto' }}>Claim a beta seat</a>
          </div>
        </div>
      </section>

      <section id="faq" className="faq">
        <div className="faq__grid">
          <h2 className="display faq__title">Frequently asked, honestly answered</h2>
          <Faq />
        </div>
      </section>

      <section id="start" className="cta">
        <div className="cta__inner grid-wash" style={{ background: 'var(--lime)', '--wash': 'rgba(16,22,19,.12)' } as CSSProperties}>
          <h2 className="display cta__title">Find out tonight. Post on Monday.</h2>
          <p className="prose cta__sub" style={{ color: '#1E2A22' }}>Paste your idea. Get the verdict, the sources, and the communities. Free, no card, and no posting on your behalf — ever.</p>
          <div className="cta__actions">
            <a href="/auth?mode=signup" className="btn btn--ink btn--lg">Validate an idea — free</a>
            <a href="#receipts" className="btn btn--lg" style={{ background: 'transparent' }}>Read a sample verdict</a>
          </div>
        </div>
      </section>

      <footer id="trust" className="site-footer slab">
        <div className="site-footer__inner">
          <div className="site-footer__grid">
            <div>
              <div className="brand" style={{ marginBottom: 14 }}>
                <span className="brand__word" style={{ color: 'var(--on-dark)' }}>deno</span>
                <span className="brand__chip">GTM</span>
              </div>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: 'var(--on-dark-dim)', maxWidth: 220 }}>The founder go-to-market workspace. Validate, then distribute — without getting filtered.</p>
            </div>
            <div className="site-footer__col">
              <div className="display site-footer__heading">Platform</div>
              <a href="#how">Validation DAG</a>
              <a href="#how">Market sizing</a>
              <a href="#how">Source ledger</a>
              <a href="#how">Community radar</a>
              <a href="/app">Content calendar</a>
            </div>
            <div className="site-footer__col">
              <div className="display site-footer__heading">Safety</div>
              <a href="#risk">Ban Risk Score</a>
              <a href="#risk">Anti-slop taxonomy</a>
              <a href="#risk">Density heuristics</a>
              <a href="#risk">Stylometry method</a>
              <a href="#trust">Human-send policy</a>
            </div>
            <div className="site-footer__col">
              <div className="display site-footer__heading">Company</div>
              <a href="#top">About</a>
              <a href="#receipts">Changelog</a>
              <a href="#pricing">Pricing</a>
              <a href="docs/01_PRD.md">Docs</a>
              <a href="mailto:hello@deno.gtm">Contact</a>
            </div>
          </div>
          <div className="site-footer__bottom">
            <span>© 2026 DENO GTM · BUILT FOR FOUNDERS WITH NO AUDIENCE</span>
            <span>NEVER POSTS · NEVER VOTES · NEVER DMs</span>
          </div>
        </div>
      </footer>

      <ScrollReveal />
    </>
  );
}
