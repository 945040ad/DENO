'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { createClient } from '@/lib/supabase/client';
import { ErrorNotice } from './ErrorNotice';

/** New-password form, built from the auth screen's existing components. */
export function ResetPassword() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
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
    if (password.length < 10) return showError('Passwords need at least 10 characters.');
    const supabase = createClient();
    if (!supabase) return showError('Sign-in is not configured yet.');
    setBusy(true);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (updateError) return showError(updateError.message);
    router.replace('/app');
  }

  return (
    <div className="auth-shell">
      <div className="auth-frame">
        <div className="auth-topbar">
          <a href="/" className="brand brand--sm">
            <span className="brand__word">deno</span>
            <span className="brand__chip">GTM</span>
          </a>
          <a href="/auth" className="mono-plain auth-topbar__back">← Back to log in</a>
        </div>

        <div className="auth-grid">
          <div className="auth-col">
            <div className="auth-heading">
              <span className="tag tag--green">Password reset</span>
              <h1 className="display auth-heading__title">Pick a new password.</h1>
              <p className="prose auth-heading__sub">At least 10 characters. You&apos;ll go straight back to your workspace.</p>
            </div>

            <form noValidate onSubmit={onSubmit}>
              <div className="field" style={{ marginBottom: 16 }}>
                <div className="field__row">
                  <label className="field__label" htmlFor="f-new-pw" style={{ marginBottom: 0 }}>New password</label>
                  <button type="button" className="mono-plain auth-linklike" onClick={() => setShowPw((s) => !s)}>{showPw ? 'hide' : 'show'}</button>
                </div>
                <input className="input" id="f-new-pw" name="password" type={showPw ? 'text' : 'password'} placeholder="At least 10 characters" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>

              <ErrorNotice message={error} nonce={nonce} />

              <button type="submit" className="btn btn--lime btn--block btn--raised" style={{ fontSize: 16, padding: 16 }} disabled={busy}>Save password</button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
