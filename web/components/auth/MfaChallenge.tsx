'use client';

import { useState, type FormEvent } from 'react';
import { createClient } from '@/lib/supabase/client';
import { ErrorNotice } from './ErrorNotice';

/** Second login step for accounts with an authenticator app, built from the auth screen's components. */
export function MfaChallenge({ next }: { next: string }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);

  function showError(message: string) {
    setError(message);
    setNonce((n) => n + 1);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = code.replace(/\s/g, '');
    if (!/^\d{6}$/.test(trimmed)) return showError('Enter the 6-digit code from your authenticator app.');
    const supabase = createClient();
    if (!supabase) return showError('Sign-in is not configured yet.');
    setBusy(true);
    try {
      const { data, error: listError } = await supabase.auth.mfa.listFactors();
      if (listError) return showError(listError.message);
      const factor = data.totp.find((f) => f.status === 'verified');
      if (!factor) {
        window.location.assign(next);
        return;
      }
      const { error: verifyError } = await supabase.auth.mfa.challengeAndVerify({ factorId: factor.id, code: trimmed });
      if (verifyError) return showError('That code didn’t match. Codes change every 30 seconds — try the current one.');
      window.location.assign(next);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-frame">
        <div className="auth-topbar">
          <a href="/" className="brand brand--sm">
            <span className="brand__word">deno</span>
            <span className="brand__chip">GTM</span>
          </a>
          <form action="/auth/signout" method="post">
            <button type="submit" className="mono-plain auth-linklike auth-topbar__back">← Use a different account</button>
          </form>
        </div>

        <div className="auth-grid">
          <div className="auth-col">
            <div className="auth-heading">
              <span className="tag tag--green">Two-factor</span>
              <h1 className="display auth-heading__title">One more step.</h1>
              <p className="prose auth-heading__sub">Open your authenticator app and enter the 6-digit code for Deno.</p>
            </div>

            <form noValidate onSubmit={onSubmit}>
              <div className="field" style={{ marginBottom: 16 }}>
                <label className="field__label" htmlFor="f-mfa-code">Code</label>
                <input
                  className="input"
                  id="f-mfa-code"
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={7}
                  placeholder="123456"
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </div>

              <ErrorNotice message={error} nonce={nonce} />

              <button type="submit" className="btn btn--lime btn--block btn--raised" style={{ fontSize: 16, padding: 16 }} disabled={busy}>Verify and continue</button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
