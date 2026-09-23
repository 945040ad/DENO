'use client';

import { useState } from 'react';
import { api, blockingFindings, warningFindings, type Audit, type GatePlatform } from '@/lib/api';
import { DeductionItems } from './Deductions';
import { paneClass } from './paneClass';

export function AuditorPane({ active }: { active: boolean }) {
  const [platform, setPlatform] = useState<GatePlatform>('reddit');
  const [text, setText] = useState('');
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runAudit() {
    const trimmed = text.trim();
    if (!trimmed) return;
    try {
      setAudit(await api.audit(trimmed, platform, platform === 'reddit' ? 'r/SaaS' : null));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const blocking = audit ? blockingFindings(audit.layers) : [];
  const warnings = audit ? warningFindings(audit.layers) : [];

  return (
    <section className={paneClass(active)} id="auditor-tab">
      <div className="section-title">
        <h2>Ban Risk &amp; Anti-Slop Studio (Playground)</h2>
        <p>Run any post through the same gates as your drafts: leaked AI phrasing, 20 AI-writing patterns, vagueness, rhythm, your voice, and community rules.</p>
      </div>

      <div className="two-col-grid">
        <div className="card">
          <div className="input-group">
            <label htmlFor="play-platform">Target Platform</label>
            <select id="play-platform" value={platform} onChange={(e) => setPlatform(e.target.value as GatePlatform)}>
              <option value="reddit">Reddit (checked against r/SaaS rules)</option>
              <option value="linkedin">LinkedIn (Outbound Link Penalty)</option>
              <option value="x">X / Twitter</option>
            </select>
          </div>
          <div className="input-group">
            <label htmlFor="play-input">Draft Content to Audit</label>
            <textarea id="play-input" rows={8} placeholder="Paste any AI-drafted or human-written post to see exactly what gets flagged and how to fix it..." value={text} onChange={(e) => setText(e.target.value)}></textarea>
          </div>
          <button className="btn-primary" id="play-audit-btn" onClick={runAudit}>⚡ Run Safety Audit</button>
        </div>

        <div className="card">
          <h3>Audit Report</h3>
          <div className="score-display-card" id="play-score-card">
            <div className="big-score" id="play-score-val">{audit ? blocking.length : '--'}</div>
            <div className="score-desc" id="play-score-desc">
              {error ?? (audit ? (audit.passed ? 'SAFE TO PUBLISH (passes every gate)' : `${blocking.length} ISSUE${blocking.length === 1 ? '' : 'S'} TO FIX BEFORE POSTING`) : 'Paste content and run audit to see what gets flagged.')}
            </div>
          </div>
          <div className="deductions-list" id="play-deductions-list">
            {audit && <DeductionItems findings={blocking} fixLabel="Fix:" />}
            {audit && warnings.length > 0 && <DeductionItems findings={warnings} fixLabel="Consider:" />}
          </div>
        </div>
      </div>
    </section>
  );
}
