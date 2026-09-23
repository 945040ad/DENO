'use client';

import { useState } from 'react';
import { api, safeHref, signal, streamEvents, type Claim, type Plan, type Report, type StreamEvent } from '@/lib/api';
import { paneClass } from './paneClass';

const HEADLINE: Record<string, string> = {
  build: 'The evidence says build it',
  pivot: 'Real pain, but reshape the offer',
  kill: 'The evidence says don’t build this',
  insufficient_evidence: 'Not enough public evidence to judge yet',
};

const TAG: Record<string, string> = {
  build: 'BUILD',
  pivot: 'PIVOT',
  kill: 'KILL',
  insufficient_evidence: 'NO CALL',
};

function fmt(value: number | null): string {
  if (value === null) return '—';
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
}

function posted(claim: Claim): string {
  const dates = claim.citations
    .filter((c) => c.verified && c.document.published_at)
    .map((c) => c.document.published_at as string)
    .sort();
  return dates.length ? new Date(dates[dates.length - 1]).toLocaleDateString() : 'undated';
}

interface Props {
  active: boolean;
  report: Report | null;
  projectId: string | null;
  runId: string | null;
  onReport: (report: Report) => void;
  onOpenCommunities: () => void;
  onPlan: (plan: Plan) => void;
  onToast: (message: string) => void;
}

export function VerdictPane({ active, report, projectId, runId, onReport, onOpenCommunities, onPlan, onToast }: Props) {
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [flagged, setFlagged] = useState<Set<string>>(() => new Set());
  const verdict = report?.verdict ?? null;
  const verified = (report?.claims ?? []).filter((c) => !c.dropped && c.citations.some((x) => x.verified));
  const competitors = verified.filter((c) => c.analyst === 'competitors');
  const docs = signal(report, 'mention_volume');
  const sources = verdict?.coverage?.by_source ?? {};
  // The rationale cites claims as [C3]; show the same labels on each claim so they can be traced.
  const labels = new Map(
    Object.entries((verdict?.coverage?.claim_refs as Record<string, string> | undefined) ?? {}).map(([k, v]) => [v, k]),
  );

  async function toggleFlag(claimId: string) {
    setFlagged((prev) => {
      const next = new Set(prev);
      if (next.has(claimId)) next.delete(claimId);
      else next.add(claimId);
      return next;
    });
  }

  async function finishReview(): Promise<void> {
    if (!runId || report?.run.status !== 'awaiting_review') return;
    await api.resume(runId, [...flagged]);
    const refreshed = await api.report(runId);
    onReport(refreshed);
  }

  async function generatePlan() {
    if (!projectId) return;
    setGenerating(true);
    setProgress('Planning posts…');
    try {
      await finishReview();
      const created = await api.createPlan(projectId, 14, runId);
      const controller = new AbortController();
      let drafted = 0;
      await streamEvents(
        created.events_url,
        (raw) => {
          const ev = JSON.parse(raw) as StreamEvent;
          if (ev.type === 'node_finished' && ev.node === 'brief_planner') setProgress(`${String(ev.briefs)} posts planned. Writing and checking drafts…`);
          if (ev.type === 'node_finished' && ev.node === 'draft') {
            drafted += 1;
            setProgress(`${drafted} drafts written and gated…`);
          }
          if (ev.type === 'status' && (ev.status === 'succeeded' || ev.status === 'failed')) controller.abort();
        },
        controller.signal,
      ).catch(() => undefined);
      const plan = await api.plan(created.plan_id);
      if (plan.status === 'failed') throw new Error('The content plan failed. Try again in a minute.');
      onPlan(plan);
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
      setProgress('');
    }
  }

  return (
    <section className={paneClass(active)} id="verdict-tab">
      <div className="verdict-banner" id="verdict-banner">
        <div className="verdict-left">
          <div className={verdict ? `verdict-tag verdict-${verdict.verdict === 'insufficient_evidence' ? 'pivot' : verdict.verdict}` : 'verdict-tag'} id="verdict-badge">
            {verdict ? TAG[verdict.verdict] : '—'}
          </div>
          <h2 id="verdict-title">{verdict ? HEADLINE[verdict.verdict] : 'No verdict yet'}</h2>
          <p id="verdict-market-desc">{verdict?.rationale ?? 'Run a validation to see what the evidence says.'}</p>
        </div>
        <div className="verdict-right">
          <div className="confidence-circle">
            <span className="confidence-val" id="confidence-val">{verdict ? `${Math.round(verdict.confidence * 100)}%` : '—'}</span>
            <span className="confidence-lbl">Evidence Confidence</span>
          </div>
        </div>
      </div>

      <div className="two-col-grid">
        <div className="card">
          <h3>Why This Verdict</h3>
          <ul className="reasons-list" id="top-reasons-list">
            {verdict?.reasons.map((reason, i) => <li key={i}>{reason}</li>)}
            {verdict?.verdict === 'insufficient_evidence' &&
              (verdict.coverage.gaps ?? []).slice(0, 3).map((gap, i) => <li key={`gap-${i}`}>{gap}</li>)}
          </ul>
        </div>

        <div className="card">
          <h3>Measured Signals</h3>
          <div className="tam-grid">
            <div className="tam-box">
              <span className="tam-label">POSTS</span>
              <span className="tam-num" id="tam-num">{fmt(docs)}</span>
            </div>
            <div className="tam-box">
              <span className="tam-label">PAY TALK</span>
              <span className="tam-num" id="sam-num">{fmt(signal(report, 'wtp_phrase_count'))}</span>
            </div>
            <div className="tam-box">
              <span className="tam-label">RIVALS</span>
              <span className="tam-num" id="som-num">{fmt(signal(report, 'competitor_mentions'))}</span>
            </div>
          </div>
          <p className="tam-calc" id="tam-calc">
            {report
              ? `Counted from the collected posts, not estimated: ${Object.entries(sources)
                  .map(([s, n]) => `${s} ${n}`)
                  .join(', ') || 'no sources'}. ${fmt(signal(report, 'claims_supporting'))} verified claims support the idea, ${fmt(signal(report, 'claims_refuting'))} cut against it.`
              : ''}
          </p>
        </div>
      </div>

      <div className="two-col-grid">
        <div className="card">
          <h3>Competitors People Mention</h3>
          <div className="competitor-list" id="competitor-list">
            {competitors.length === 0 && report && <p style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>No verified competitor mentions in the evidence.</p>}
            {competitors.map((c) => {
              const cite = c.citations.find((x) => x.verified);
              return (
                <div className="competitor-card" key={c.id}>
                  <h4>{labels.get(c.id) ? `${labels.get(c.id)} · ` : ''}<a href={safeHref(cite?.document.url)} target="_blank" rel="noopener noreferrer">{cite?.document.source ?? 'source'}</a> · <span style={{ fontWeight: 400, color: 'var(--muted)' }}>{c.stance}</span></h4>
                  <p style={{ fontSize: '0.85rem', color: 'var(--ink-3)' }}>{c.text}</p>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card">
          <h3>Clickable Source Ledger</h3>
          <div className="source-list" id="source-ledger-list">
            {verified
              .filter((c) => c.analyst !== 'competitors')
              .map((c) => {
                const cite = c.citations.find((x) => x.verified);
                return (
                  <div className="source-item" key={c.id}>
                    <a href={safeHref(cite?.document.url)} target="_blank" rel="noopener noreferrer">
                      🔗 {labels.get(c.id) ? `${labels.get(c.id)} · ` : ''}{cite?.document.community ?? cite?.document.source} · {c.analyst}
                    </a>
                    <p>{c.text}</p>
                    <div className="source-date">
                      Posted {posted(c)} · {c.stance}
                      {report?.run.status === 'awaiting_review' && (
                        <>
                          {' · '}
                          <button className="btn-ghost" style={{ padding: 0, fontSize: 'inherit' }} onClick={() => toggleFlag(c.id)}>
                            {flagged.has(c.id) ? '✓ flagged as wrong' : 'flag as wrong'}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      </div>

      <div className="action-footer">
        <button className="btn-secondary" id="open-communities-btn" onClick={onOpenCommunities}>Explore Community Targets →</button>
        <button className="btn-primary" id="generate-calendar-btn" disabled={generating || !projectId} onClick={generatePlan}>
          {generating ? progress || 'Writing drafts…' : '⚡ Generate 14-Day Safe Content Plan'}
        </button>
      </div>
    </section>
  );
}
