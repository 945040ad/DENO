'use client';

import { useEffect, useState } from 'react';
import { api, safeHref, type Community } from '@/lib/api';
import { paneClass } from './paneClass';

export function CommunitiesPane({ active, runId }: { active: boolean; runId: string | null }) {
  const [communities, setCommunities] = useState<Community[]>([]);

  useEffect(() => {
    if (!runId || !active) return;
    let cancelled = false;
    api
      .runCommunities(runId)
      .then((rows) => !cancelled && setCommunities(rows))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId, active]);

  return (
    <section className={paneClass(active)} id="communities-tab">
      <div className="section-title">
        <h2>Target Communities &amp; Rule Radar</h2>
        <p>Where the evidence for your idea was posted, with each community&apos;s rules when we have them on file.</p>
      </div>
      <div className="community-grid" id="community-grid">
        {communities.length === 0 && <p style={{ color: 'var(--muted)' }}>{runId ? 'No community data for this run.' : 'Run a validation first.'}</p>}
        {communities.map((c) => (
          <div className="community-card" key={c.id}>
            <div className="community-header">
              <h4 style={{ fontSize: '1.05rem' }}><a href={safeHref(c.url ?? `https://www.reddit.com/${c.name}/`)} target="_blank" rel="noopener noreferrer">{c.name}</a></h4>
              <span className="community-pill">{c.platform.toUpperCase()}</span>
            </div>
            <div className="rule-row"><span className="rule-label">Posts found:</span> <span>{c.evidence_count ?? '—'}</span></div>
            <div className="rule-row"><span className="rule-label">Gate:</span> <span>{c.karma_gate ?? 'Not on file'}</span></div>
            <div className="rule-row"><span className="rule-label">Self-Promo:</span> <span>{c.promo_policy ?? 'Not on file: read the sidebar'}</span></div>
            <div className="rule-row"><span className="rule-label">Cadence:</span> <span>{c.cadence ?? 'Not on file'}</span></div>
            <p style={{ fontSize: '0.8rem', color: 'var(--red-ink)', marginTop: '0.5rem' }}>
              <strong style={{ color: 'var(--muted)' }}>AI Rule:</strong> {c.ai_policy ?? 'Unknown; assume AI posts get removed.'}
              {c.promo_policy && !c.rules_verified && <span style={{ color: 'var(--muted)' }}> (rules not yet re-checked against the live page)</span>}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
