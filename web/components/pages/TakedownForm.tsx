'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

export function TakedownForm() {
  const [url, setUrl] = useState('');
  const [handle, setHandle] = useState('');
  const [reason, setReason] = useState('');
  const [contact, setContact] = useState('');
  const [result, setResult] = useState<string | null>(null);

  async function submit() {
    try {
      const receipt = await api.takedown({
        url: url.trim() || null,
        author_handle: handle.trim() || null,
        reason: reason.trim(),
        contact: contact.trim() || null,
      });
      setResult(`Received (reference ${receipt.id}). We review requests within 7 days and remove matching content everywhere in Deno.`);
    } catch (err) {
      setResult(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="card intake-card">
      <div className="input-group">
        <label htmlFor="td-url">Link to the post (optional if you give a handle)</label>
        <input id="td-url" type="url" placeholder="https://www.reddit.com/r/…" value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
      <div className="input-group">
        <label htmlFor="td-handle">Or your handle, to remove everything you wrote</label>
        <input id="td-handle" type="text" placeholder="u/yourname or @yourname" value={handle} onChange={(e) => setHandle(e.target.value)} />
      </div>
      <div className="input-group">
        <label htmlFor="td-reason">Why should it be removed?</label>
        <textarea id="td-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)}></textarea>
      </div>
      <div className="input-group">
        <label htmlFor="td-contact">Email for the outcome (optional)</label>
        <input id="td-contact" type="email" value={contact} onChange={(e) => setContact(e.target.value)} />
      </div>
      <button className="btn-primary" disabled={reason.trim().length < 3 || (!url.trim() && !handle.trim())} onClick={submit}>Send Request</button>
      {result && <p style={{ marginTop: '1rem' }}>{result}</p>}
    </div>
  );
}
