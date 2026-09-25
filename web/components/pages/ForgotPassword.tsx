'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send() {
    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) return setError('Enter a valid email address.');
    const supabase = createClient();
    if (!supabase) return setError('Login is not configured on this server.');
    setBusy(true);
    const origin = process.env.NEXT_PUBLIC_SITE_URL || window.location.origin;
    const { error: err } = await supabase.auth.resetPasswordForEmail(trimmed, {
      redirectTo: `${origin}/auth/callback?next=${encodeURIComponent('/auth/reset')}`,
    });
    setBusy(false);
    // Same answer whether or not the address has an account (no account enumeration).
    if (err && !/not found|user/i.test(err.message)) return setError(err.message);
    setSent(true);
  }

  return (
    <div className="dv-split wide dv-rise">
      <div className="dv-pad lg dv-rr">
        <span className="dv-kicker">RESET PASSWORD</span>
        <h1 className="dv-h1" style={{ fontSize: 'clamp(32px,3.6vw,50px)', margin: '20px 0 12px' }}>Locked out? One link fixes it.</h1>
        {!sent ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 460 }}>
            <p className="dv-lede" style={{ marginBottom: 8 }}>Enter your account email and we&apos;ll send a link to set a new password.</p>
            <label className="dv-label" style={{ marginBottom: 0 }}>EMAIL</label>
            <input className="dv-input" type="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} placeholder="you@founder.dev" onKeyDown={(e) => e.key === 'Enter' && send()} />
            {error && <div className="dv-err"><span className="dv-mono" style={{ fontWeight: 700, color: 'var(--red-ink)' }}>ERR</span>{error}</div>}
            <button className="dv-btn lime" style={{ fontSize: 16, padding: 16, marginTop: 4 }} disabled={busy} onClick={send}>{busy ? 'Sending…' : 'Send reset link'}</button>
            <a href="/auth" className="dv-link" style={{ alignSelf: 'flex-start', marginTop: 6 }}>← Back to log in</a>
          </div>
        ) : (
          <div className="dv-ok dv-rise" style={{ maxWidth: 460 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, color: 'var(--green)' }}>
              <span className="dv-dot" />
              <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em' }}>LINK SENT</span>
            </div>
            <p style={{ margin: '0 0 16px', fontSize: 14.5, lineHeight: 1.6 }}>If {email.trim()} has an account, a reset link is on its way. Check spam if it&apos;s not there in a minute.</p>
            <button className="dv-btn ghost" onClick={() => setSent(false)}>Use a different email</button>
          </div>
        )}
      </div>
      <div className="dv-pad lg dv-dark" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', gap: 10, minHeight: 320 }}>
        <span className="dv-dark-label">NOTHING POSTS WITHOUT YOU</span>
        <div className="dv-serif" style={{ fontSize: 'clamp(26px,3vw,40px)', lineHeight: 1.05 }}>Every draft waits for a human send. Nothing was posted while you were locked out.</div>
      </div>
    </div>
  );
}
