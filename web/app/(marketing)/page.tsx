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
        <a href="#pricing" className="announce__pill">
          <span className="tag tag--green" style={{ background: 'var(--green)', color: '#fff', borderColor: 'var(--green)' }}>New</span>
          <span className="announce__text">The beta is open. Everything is free while we build.</span>
          <span className="announce__cta">See what&apos;s included →</span>
        </a>
      </section>

      <section className="hero">
        <h1 className="display hero__title">Know if it&apos;s worth building.<br />Then go get your first 100 users.</h1>
        <p className="prose hero__sub">Research agents read what people actually posted about your problem on Reddit, Hacker News, X and Product Hunt, and every claim links to the post it came from. Then Deno drafts up to thirty days of posts in your voice, each one checked before you press send.</p>
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
                <span className="mono" style={{ color: 'var(--muted)' }}>Example run</span>
                <span className="pulse-dot"></span>
              </div>
              <div className="display" style={{ fontSize: 'clamp(30px,3.4vw,44px)' }}>PIVOT</div>
              <div className="hero-strip__confidence">
                <span className="display" style={{ fontSize: 30, color: 'var(--green)' }}>65%</span>
                <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>confidence, computed from the evidence</span>
              </div>
              <div className="hero-strip__agents">
                <div><span style={{ color: 'var(--green)' }}>✓</span> Sources collected · 89 posts</div>
                <div><span style={{ color: 'var(--green)' }}>✓</span> Citation judge · 21 claims verified</div>
                <div><span style={{ color: 'var(--green)' }}>✓</span> Critic (adversarial)</div>
                <div style={{ color: 'var(--muted)' }}><span>⟳</span> Verdict</div>
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
              <span className="mono">Slop scrub · 20 patterns</span>
              <div className="hero-strip__scrub">
                <div><span className="hero-strip__strike">In today&apos;s fast-paced world</span> −5</div>
                <div><span className="hero-strip__strike">It&apos;s not just X — it&apos;s Y</span> −5</div>
                <div><span className="hero-strip__strike">Let&apos;s dive in 🚀</span> −5</div>
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 'auto' }}>Every flag points at the exact words and says what to change.</div>
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
              <span className="mono-plain" style={{ position: 'absolute', right: 28, bottom: 22, color: 'var(--green)' }}>SOURCE LEDGER</span>
            </div>
            <div className="wall-card__body">
              <p className="prose" style={{ color: 'var(--ink-2)' }}>Paste the idea. Deno collects real posts, analysts argue from what they find, a critic attacks the result, and a judge checks every claim against the post it cites. Claims it can&apos;t verify are dropped.</p>
              <a href="/app" className="link-mono">Run the DAG →</a>
            </div>
          </div>

          <div className="wall-card" style={{ background: 'var(--peach)' }}>
            <div className="wall-card__head">
              <span className="display" style={wallTitle}>Stage 2 — Distribution</span>
              <span className="tag tag--ink" style={inkTag}>Free in beta</span>
            </div>
            <div className="wall-card__art grid-wash grid-wash--peach">
              <div className="wall-card__bar-1"></div>
              <div className="wall-card__bar-2"></div>
              <div className="wall-card__bar-3"></div>
              <div className="wall-card__dot"></div>
            </div>
            <div className="wall-card__body">
              <p className="prose" style={{ color: '#3A2A22' }}>A 7, 14 or 30-day calendar with irregular cadence, at most one promotional post in ten, and none in communities that ban promotion. Checked against your own writing samples, not a house voice.</p>
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
              <p className="prose" style={{ color: '#1E2A38' }}>Twenty structural slop patterns, word-density checks and the rules of the community you&apos;re posting in — itemised with what to fix, before your account is on the line.</p>
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
              <h2 className="display riskband__title">Moderators spot a generated post in one line. Check yours first.</h2>
              <p className="prose riskband__sub" style={{ color: 'var(--on-dark-soft)' }}>Paste any draft — ours or yours. The scrubber runs twenty structural slop patterns, the density check catches stacked AI vocabulary, and the rule check reads the community you&apos;re aiming at. You get one number and a fix list.</p>
              <div className="riskband__actions">
                <a href="/app" className="btn btn--lime">Score a draft free</a>
                <a href="#faq" className="btn" style={{ color: 'var(--on-dark)', borderColor: 'rgba(250,248,243,.4)' }}>How it decides</a>
              </div>
            </div>

            <div className="risk-card">
              <div className="risk-card__top">
                <div className="risk-card__score">
                  <span className="display" style={{ fontSize: 'clamp(46px,6vw,72px)' }}>90</span>
                  <span className="mono-plain" style={{ textAlign: 'center', color: 'var(--ink)' }}>Ban Risk<br />Score</span>
                </div>
                <div className="risk-card__meta">
                  <span className="mono-plain">Example · r/SaaS · self-promotion limited</span>
                  <span style={{ fontSize: 14.5, fontWeight: 600, lineHeight: 1.4 }}>Passes every gate. Two small fixes suggested.</span>
                </div>
              </div>
              <div className="risk-card__deductions">
                <div className="mono-plain" style={{ marginBottom: 10 }}>Itemised deductions</div>
                <div className="risk-card__item" style={{ background: 'var(--peach)' }}><span className="risk-card__pt" style={{ color: 'var(--red-ink)' }}>−5</span><span>Rule-of-three rhythm ×4 · <span style={{ color: 'var(--muted)' }}>break two of the triads into single clauses</span></span></div>
                                <div className="risk-card__item" style={{ background: 'var(--amber-soft)' }}><span className="risk-card__pt" style={{ color: 'var(--amber)' }}>−5</span><span>Outbound link in body · <span style={{ color: 'var(--muted)' }}>move to first comment</span></span></div>
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
          <div className="receipt-stat" style={{ background: 'var(--green-soft)' }}><span className="display">7</span><span>analyst agents, plus a critic whose only job is to argue against them</span></div>
          <div className="receipt-stat" style={{ background: 'var(--peach)', color: '#3A2A22' }}><span className="display">20</span><span>structural slop patterns, each flagged at the exact words</span></div>
          <div className="receipt-stat" style={{ background: 'var(--blue-soft)', color: '#1E2A38' }}><span className="display">12</span><span>communities mapped with their rules, karma gates and promo limits</span></div>
          <div className="receipt-stat" style={{ background: 'var(--lime)' }}><span className="display">0</span><span>posts, votes or DMs sent automatically. A human always presses send.</span></div>
        </div>

        <div className="receipts__cards">
          <div className="receipt-slot">
            <span className="mono-plain">Testimonial slot 01</span>
            <span className="display" style={{ fontSize: 22, lineHeight: 1.2, color: 'var(--muted)' }}>Reserved for the first founder who ships with Deno.</span>
            <span style={{ fontSize: 13, color: 'var(--muted)', marginTop: 'auto' }}>The beta is open now.</span>
          </div>
          <div className="receipt-note panel">
            <span className="mono-plain">Built in public</span>
            <span style={{ fontSize: 15, lineHeight: 1.55, color: 'var(--ink-2)' }}>Every verdict Deno produces is auditable: unit tests across the scoring engines, and a source ledger with retrieval timestamps on every claim.</span>
            <a href="#faq" className="link-mono" style={{ marginTop: 'auto' }}>Read how it decides →</a>
          </div>
        </div>
      </section>

      <section id="pricing" className="pricing">
        <div className="pricing__head">
          <span className="tag tag--blue">Pricing</span>
          <h2 className="display pricing__title">Free while in beta.</h2>
        </div>
        <div className="pricing__grid">
          <div className="price-card">
            <span className="mono">Stage 1</span>
            <span className="display" style={{ fontSize: 52 }}>$0</span>
            <div className="price-card__list">
              <span>5 idea validations a month</span>
              <span>Build / Pivot / Kill, or &ldquo;not enough evidence&rdquo;</span>
              <span>Every claim linked to its source post</span>
              <span>Kept and dropped claims, side by side</span>
              <span>12 communities with their rules</span>
            </div>
            <a href="/auth?mode=signup" className="btn" style={{ marginTop: 'auto' }}>Start validating</a>
          </div>
          <div className="price-card price-card--featured">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span className="mono">Stage 2</span>
              <span className="tag tag--ink">Beta</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <span className="display" style={{ fontSize: 52 }}>$0</span>
              <span style={{ fontSize: 14, fontWeight: 600 }}>during beta</span>
            </div>
            <div className="price-card__list">
              <span>Everything in Stage 1</span>
              <span>1 content plan a month, 7 to 30 days</span>
              <span>Ban Risk Score on every draft, 200 audits a month</span>
              <span>Slop, density, rhythm and community-rule checks</span>
              <span>Story Bank &amp; voice matching</span>
              <span>Paid plans come later; beta users hear first</span>
            </div>
            <a href="/auth?mode=signup" className="btn btn--ink" style={{ marginTop: 'auto' }}>Join the beta</a>
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
              <a href="#how">Verdicts</a>
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
              <a href="#faq">FAQ</a>
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
