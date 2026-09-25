'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

export function TakedownForm() {
  const [url, setUrl] = useState('');
  const [handle, setHandle] = useState('');
  const [reason, setReason] = useState('');
  const [contact, setContact] = useState('');
  const [receipt, setReceipt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ok = reason.trim().length >= 3 && Boolean(url.trim() || handle.trim());

  async function submit() {
    if (!ok) return;
    try {
      const r = await api.takedown({ url: url.trim() || null, author_handle: handle.trim() || null, reason: reason.trim(), contact: contact.trim() || null });
      setReceipt(r.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const field = (label: string, value: string, set: (v: string) => void, placeholder: string, type = 'text') => (
    <div>
      <label className="dv-label">{label}</label>
      <input className="dv-input" type={type} value={value} placeholder={placeholder} onChange={(e) => { set(e.target.value); setError(null); }} />
    </div>
  );

  return (
    <div className="dv-split wide dv-rise">
      <div className="dv-pad lg dv-rr">
        <span className="dv-kicker red">TAKEDOWN REQUEST</span>
        <h1 className="dv-h1" style={{ fontSize: 'clamp(32px,3.6vw,50px)', margin: '20px 0 12px' }}>Remove something we indexed.</h1>
        <p className="dv-lede" style={{ marginBottom: 22, maxWidth: 480 }}>Deno reads public posts as evidence when a founder runs a validation. If one of yours shows up and you want it out, tell us. No account needed.</p>
        {!receipt ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 520 }}>
            {field('LINK TO THE POST', url, setUrl, 'https://reddit.com/r/…', 'url')}
            {field('OR YOUR HANDLE · REMOVES EVERYTHING', handle, setHandle, 'u/yourname or @yourname')}
            <div>
              <label className="dv-label">REASON</label>
              <textarea className="dv-input" rows={3} value={reason} placeholder="A sentence is enough." onChange={(e) => { setReason(e.target.value); setError(null); }} />
            </div>
            {field('EMAIL FOR THE OUTCOME · OPTIONAL', contact, setContact, 'you@example.com', 'email')}
            {error && <div className="dv-err"><span className="dv-mono" style={{ fontWeight: 700, color: 'var(--red-ink)' }}>ERR</span>{error}</div>}
            <button className="dv-btn ink" style={{ alignSelf: 'flex-start' }} disabled={!ok} onClick={submit}>Send request</button>
          </div>
        ) : (
          <div className="dv-ok dv-rise" style={{ maxWidth: 520 }}>
            <div className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em', color: 'var(--green)', marginBottom: 10 }}>RECEIPT · {receipt.slice(0, 8).toUpperCase()}</div>
            <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6 }}>Received. A person reviews every request within 7 days; approved requests are removed from every report across Deno.</p>
          </div>
        )}
      </div>
      <div className="dv-pad lg dv-soft" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <span className="dv-label" style={{ letterSpacing: '.12em', marginBottom: 6 }}>WHAT HAPPENS NEXT</span>
        {[
          'A person reviews the request, usually within 7 days.',
          'If approved, the post text is purged from every report and search index in Deno.',
          'Reports keep only the bare link, so nobody sees the removed text.',
        ].map((t, i) => (
          <div key={t} className="dv-card" style={{ display: 'flex', gap: 12 }}>
            <span className="dv-mono" style={{ fontSize: 11, fontWeight: 700 }}>0{i + 1}</span>
            <span style={{ fontSize: 14, lineHeight: 1.5 }}>{t}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
