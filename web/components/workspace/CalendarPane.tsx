'use client';

import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { api, blockingFindings, warningFindings, type Brief, type GateLayer, type Plan } from '@/lib/api';
import { DeductionItems } from './Deductions';
import { paneClass } from './paneClass';

const PLATFORM_LINKS: Record<string, string> = {
  reddit: 'https://www.reddit.com/submit',
  linkedin: 'https://www.linkedin.com/feed/',
  x: 'https://x.com/compose/post',
};

function pillStyles(issues: number): { boxClass: string; boxStyle?: CSSProperties; scoreStyle: CSSProperties } {
  if (issues === 0) return { boxClass: 'score-pill-box', boxStyle: { borderColor: 'var(--green)' }, scoreStyle: { color: 'var(--green)' } };
  if (issues <= 2) return { boxClass: 'score-pill-box score-warning', scoreStyle: { color: 'var(--amber)' } };
  return { boxClass: 'score-pill-box score-danger', scoreStyle: { color: 'var(--red)' } };
}

interface Props {
  active: boolean;
  plan: Plan | null;
  onPlan: (plan: Plan) => void;
  onToast: (message: string) => void;
}

export function CalendarPane({ active, plan, onPlan, onToast }: Props) {
  const briefs = (plan?.briefs ?? []).filter((b) => b.draft);
  const [selected, setSelected] = useState(0);
  const [content, setContent] = useState('');
  const [layers, setLayers] = useState<GateLayer[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const debounce = useRef<number | undefined>(undefined);
  const brief: Brief | undefined = briefs[selected];

  function load(index: number, list: Brief[]) {
    const next = list[index];
    setSelected(index);
    setDirty(false);
    if (!next?.draft) return;
    setContent(next.draft.text);
    setLayers(next.draft.gates);
  }

  // A new plan opens on its first draft; a refreshed copy of the same plan keeps the current draft.
  const planIdRef = useRef<string | null>(null);
  useEffect(() => {
    const samePlan = plan?.id === planIdRef.current;
    planIdRef.current = plan?.id ?? null;
     
    load(samePlan ? selected : 0, (plan?.briefs ?? []).filter((b) => b.draft));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to plan changes
  }, [plan]);

  useEffect(() => () => window.clearTimeout(debounce.current), []);

  function onContentChange(text: string) {
    setContent(text);
    setDirty(true);
    window.clearTimeout(debounce.current);
    const platform = brief?.platform === 'reddit' ? 'reddit' : 'linkedin';
    debounce.current = window.setTimeout(() => {
      api
        .audit(text, platform, brief?.community)
        .then((a) => setLayers(a.layers))
        .catch(() => {
          /* keep the last audit on failure */
        });
    }, 400);
  }

  async function refresh() {
    if (plan) onPlan(await api.plan(plan.id));
  }

  /** Saves the edit as a new version; returns that version's id (null when nothing was saved). */
  async function save(quiet = false): Promise<string | null> {
    if (!brief?.draft) return null;
    setSaving(true);
    try {
      const updated = await api.editDraft(brief.draft.id, content);
      setLayers(updated.gates);
      setDirty(false);
      if (!quiet) {
        await refresh();
        onToast(updated.status === 'gated' ? 'Saved. Passes every gate.' : 'Saved. Some gates still flag it.');
      }
      return updated.id;
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function approve() {
    if (!brief?.draft) return;
    try {
      const draftId = dirty ? await save(true) : brief.draft.id;
      if (!draftId) return;
      await api.approveDraft(draftId);
      await refresh();
      onToast('Approved. Copy it and post it yourself when you are ready.');
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err));
    }
  }

  const blocking = blockingFindings(layers);
  const warnings = warningFindings(layers);
  const pill = pillStyles(blocking.length);
  const status = brief?.draft?.status;

  return (
    <section className={paneClass(active)} id="calendar-tab">
      <div className="section-title">
        <h2>{plan ? `${plan.days}-Day` : ''} Platform-Safe Content Plan</h2>
        <p>Written in your voice from your Story Bank, checked against AI-writing patterns and each community&apos;s rules. You review and press send.</p>
      </div>

      <div className="calendar-layout">
        <div className="calendar-sidebar" id="calendar-asset-list">
          {briefs.map((b, idx) => (
            <div key={b.id} className={`asset-nav-item ${idx === selected ? 'active' : ''}`} onClick={() => load(idx, briefs)}>
              <div className="asset-day">Day {b.day} · {b.platform.toUpperCase()} · {b.draft?.status}</div>
              <div className="asset-title">{b.angle}</div>
              <span className="community-pill" style={{ fontSize: '0.75rem' }}>{b.community ?? 'Feed'}{b.is_promotional ? ' · promo' : ''}</span>
            </div>
          ))}
        </div>

        <div className="calendar-editor-card card">
          <div className="editor-header">
            <div>
              <span className="tag tag--ink" id="editor-platform-badge">{brief?.platform.toUpperCase() ?? '—'}</span>
              {' '}
              <span className="community-pill" id="editor-community-badge">{brief?.community ?? 'Feed'}</span>
            </div>
            <div className={pill.boxClass} id="editor-score-pill" style={pill.boxStyle}>
              <span className="score-num" id="editor-ban-score" style={pill.scoreStyle}>{brief ? blocking.length : '—'}</span>
              <span className="score-lbl">Issues To Fix</span>
            </div>
          </div>

          <div className="input-group">
            <label htmlFor="editor-content">Post Copy (Editable in place{status ? ` · ${status}` : ''})</label>
            <textarea id="editor-content" rows={10} value={content} onChange={(e) => onContentChange(e.target.value)}></textarea>
          </div>

          <div className="input-group" id="editor-first-comment-group">
            <label htmlFor="editor-first-comment">Angle for This Post</label>
            <input type="text" id="editor-first-comment" readOnly value={brief ? `${brief.angle} (hook ${brief.hook_formula ?? '-'})` : ''} />
          </div>

          <div className="deductions-container">
            <h4>Safety &amp; Anti-Slop Audit (Live)</h4>
            <div className="deductions-list" id="editor-deductions-list">
              {brief && blocking.length === 0 ? (
                <p style={{ color: 'var(--green)', fontSize: '0.9rem' }}>✓ Passes every gate: no AI-writing patterns, unsourced numbers or rule conflicts found.</p>
              ) : (
                <DeductionItems findings={blocking} fixLabel="Suggested Fix:" />
              )}
              {warnings.length > 0 && <DeductionItems findings={warnings} fixLabel="Consider:" />}
            </div>
          </div>

          <div className="editor-footer">
            <div className="compliance-note">
              <span className="lock-icon">🔒</span> Deno never posts automatically. You always review and press send.
            </div>
            <div className="button-group">
              {dirty && (
                <button className="btn-secondary" disabled={saving} onClick={() => void save()}>💾 Save &amp; Re-check</button>
              )}
              {status !== 'approved' && status !== 'exported' && (
                <button className="btn-secondary" disabled={!brief || blocking.length > 0} onClick={approve}>✓ Approve</button>
              )}
              <button
                className="btn-secondary"
                id="copy-post-btn"
                onClick={() => {
                  void navigator.clipboard.writeText(content);
                  if (brief?.draft && status === 'approved') void api.exportDraft(brief.draft.id).then(refresh).catch(() => undefined);
                  onToast('Post copied to clipboard! You are ready to publish.');
                }}
              >
                📋 Copy Post
              </button>
              <a href={PLATFORM_LINKS[brief?.platform ?? 'reddit'] ?? PLATFORM_LINKS.reddit} target="_blank" rel="noopener noreferrer" className="btn-primary" id="open-platform-link">
                Open Platform ↗
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
