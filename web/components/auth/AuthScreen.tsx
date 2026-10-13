'use client';

import { useState, type FormEvent } from 'react';
import { createClient, setRememberPreference } from '@/lib/supabase/client';
import { AuthTopbar } from './AuthTopbar';
import { ErrorNotice } from './ErrorNotice';

export type AuthMode = 'login' | 'signup';

interface Pending {
  label: string;
  title: string;
  body: string;
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function computeStrength(pw: string): { pct: string; label: string; color: string } {
  let s = 0;
  if (pw.length >= 10) s++;
  if (pw.length >= 14) s++;
  if (/[^a-zA-Z0-9]/.test(pw)) s++;
  if (/[0-9]/.test(pw) && /[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
  if (!pw) return { pct: '0%', label: 'EMPTY', color: 'var(--lime)' };
  if (s <= 1) return { pct: '28%', label: 'WEAK', color: 'var(--red)' };
  if (s === 2) return { pct: '56%', label: 'OK', color: '#C8A21A' };
  if (s === 3) return { pct: '80%', label: 'STRONG', color: 'var(--green)' };
  return { pct: '100%', label: 'EXCELLENT', color: 'var(--green)' };
}

function siteOrigin(): string {
  return process.env.NEXT_PUBLIC_SITE_URL || window.location.origin;
}

function callbackUrl(next: string): string {
  return `${siteOrigin()}/auth/callback?next=${encodeURIComponent(next)}`;
}

interface Props {
  initialMode: AuthMode;
  next: string;
  initialError: string | null;
  /** False when no Supabase project is configured (local dev without keys). */
  authEnabled: boolean;
}

export function AuthScreen({ initialMode, next, initialError, authEnabled }: Props) {
  const [mode, setModeState] = useState<AuthMode>(initialMode);
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);
  const [agree, setAgree] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(initialError);
  const [errorNonce, setErrorNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const isLogin = mode === 'login';
  // The meter only tracks typing while in sign-up mode, like the original.
  const [strength, setStrength] = useState(() => computeStrength(''));

  function showError(message: string) {
    setError(message);
    setErrorNonce((n) => n + 1);
  }

  function setMode(nextMode: AuthMode) {
    setModeState(nextMode);
    setPending(null);
    setError(null);
  }

  function onPasswordChange(value: string) {
    setPassword(value);
    if (mode === 'signup') setStrength(computeStrength(value));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmedEmail = email.trim();
    const trimmedName = name.trim();

    if (!trimmedEmail || !EMAIL_RE.test(trimmedEmail)) return showError('Enter a valid email address.');
    if (isLogin ? password.length < 1 : password.length < 10) {
      return showError(isLogin ? 'Enter your password.' : 'Passwords need at least 10 characters.');
    }
    if (!isLogin && !trimmedName) return showError('Add your name — posts get written in your voice.');
    if (!isLogin && !agree) return showError('Accept the terms and human-send policy to continue.');

    const supabase = createClient();
    if (!supabase) return showError('Sign-in is not configured yet. Use the skip link above for now.');

    setBusy(true);
    try {
      if (isLogin) {
        setRememberPreference(remember);
        const { error: signInError } = await supabase.auth.signInWithPassword({ email: trimmedEmail, password });
        if (signInError) return showError(signInError.message);
        setPending({
          label: 'AUTHENTICATING',
          title: 'Opening your workspace…',
          body: 'Loading your projects, verdicts and drafts. Nothing was posted while you were away.',
        });
        window.location.assign(next);
        return;
      }

      setRememberPreference(true);
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: trimmedEmail,
        password,
        options: { data: { full_name: trimmedName }, emailRedirectTo: callbackUrl(next) },
      });
      if (signUpError) return showError(signUpError.message);
      if (data.session) {
        // Email confirmation is off for this project: already signed in.
        window.location.assign(next);
        return;
      }
      setPending({
        label: 'CHECK YOUR INBOX',
        title: "One link to confirm, then you're in.",
        body: `We sent a confirmation link to ${trimmedEmail || 'your email'}. No card, no onboarding call — the first validation run starts the moment you click it.`,
      });
    } finally {
      setBusy(false);
    }
  }

  async function onGoogle() {
    setError(null);
    const supabase = createClient();
    if (!supabase) return showError('Sign-in is not configured yet. Use the skip link above for now.');
    setRememberPreference(isLogin ? remember : true);
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: callbackUrl(next) },
    });
    if (oauthError) showError(oauthError.message);
  }

  return (
    <div className="auth-shell">
      <div className="auth-frame">

        <AuthTopbar mode={mode} onMode={setMode} />

        {!authEnabled && (
          <div className="auth-devskip">
            <a href="/app" className="mono-plain auth-devskip__link">Skip login for now — auth isn&apos;t required yet →</a>
          </div>
        )}

        <div className="auth-grid">

          <div className="auth-col">

            <div id="heading-login" className="auth-heading" hidden={!isLogin}>
              <span className="tag tag--green">Welcome back</span>
              <h1 className="display auth-heading__title">Pick up where the critic left off.</h1>
              <p className="prose auth-heading__sub">Your verdicts, source ledgers and 30-day calendars are exactly where you left them. Nothing was posted while you were gone.</p>
            </div>

            <div id="heading-signup" className="auth-heading" hidden={isLogin}>
              <span className="tag tag--lime">Stage 1 · Free · No card</span>
              <h1 className="display auth-heading__title">Validate your first idea in a few minutes.</h1>
              <p className="prose auth-heading__sub">One account, five validations a month, free during the beta. The content calendar and Ban Risk Studio are included.</p>
            </div>

            <div id="pending-panel" className="auth-pending rise" hidden={!pending}>
              <div className="auth-pending__head">
                <span className="pulse-dot" style={{ background: 'var(--green)' }}></span>
                <span className="mono" id="pending-label" style={{ color: 'var(--green)' }}>{pending?.label ?? 'CHECK YOUR INBOX'}</span>
              </div>
              <div className="display auth-pending__title" id="pending-title">{pending?.title ?? "One link to confirm, then you're in."}</div>
              <p className="prose auth-pending__body" id="pending-body" style={{ color: 'var(--ink-2)' }}>{pending?.body}</p>
              <button type="button" className="btn" id="pending-reset" onClick={() => { setPending(null); setError(null); }}>Use a different email</button>
            </div>

            <form id="auth-form" noValidate hidden={Boolean(pending)} onSubmit={onSubmit}>
              <div id="field-name" className="field" hidden={isLogin}>
                <label className="field__label" htmlFor="f-name">Your name</label>
                <input className="input" id="f-name" name="name" type="text" placeholder="First and last" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="f-email">Email</label>
                <input className="input" id="f-email" name="email" type="email" placeholder="you@founder.dev" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>

              <div className="field" style={{ marginBottom: 8 }}>
                <div className="field__row">
                  <label className="field__label" htmlFor="f-pw" style={{ marginBottom: 0 }}>Password</label>
                  <button type="button" className="mono-plain auth-linklike" id="toggle-pw" onClick={() => setShowPw((s) => !s)}>{showPw ? 'hide' : 'show'}</button>
                </div>
                <input className="input" id="f-pw" name="password" type={showPw ? 'text' : 'password'} placeholder="At least 10 characters" autoComplete={isLogin ? 'current-password' : 'new-password'} value={password} onChange={(e) => onPasswordChange(e.target.value)} />
              </div>

              <div id="strength-row" className="auth-strength" hidden={isLogin}>
                <div className="auth-strength__track"><div className="auth-strength__fill" id="strength-fill" style={strength.label === 'EMPTY' && !password ? undefined : { width: strength.pct, background: strength.color }}></div></div>
                <span className="mono" id="strength-label">{strength.label}</span>
              </div>

              <div id="row-remember" className="auth-row-between" hidden={!isLogin}>
                <button type="button" className="check" id="chk-remember" role="checkbox" aria-checked={remember} onClick={() => setRemember((r) => !r)}>
                  <span className="check__box" id="chk-remember-box">{remember ? '✓' : ''}</span>
                  Keep me signed in
                </button>
                <a href="/forgot" className="link-mono" style={{ fontSize: 11 }}>Forgot password →</a>
              </div>

              <button type="button" className="check" id="chk-agree" role="checkbox" aria-checked={agree} hidden={isLogin} onClick={() => { setAgree((a) => !a); setError(null); }}>
                <span className="check__box" id="chk-agree-box">{agree ? '✓' : ''}</span>
                <span>I agree to the <strong>terms</strong> and the <strong>human-send policy</strong> — Deno never posts, votes or DMs on my behalf.</span>
              </button>

              <ErrorNotice message={error} nonce={errorNonce} />

              <button type="submit" className="btn btn--lime btn--block btn--raised" id="submit-btn" style={{ fontSize: 16, padding: 16 }} disabled={busy}>{isLogin ? 'Log in' : 'Create account — free'}</button>

              <div className="auth-or">
                <span></span><span className="mono-plain">OR</span><span></span>
              </div>
              <button type="button" className="btn btn--ghost btn--block" onClick={onGoogle}>Continue with Google</button>

              <div className="auth-switch-row">
                <span id="switch-prompt" style={{ fontSize: 14, color: 'var(--ink-3)' }}>{isLogin ? 'No account yet?' : 'Already validating with Deno?'}</span>
                <button type="button" className="link-mono" id="switch-mode" style={{ fontSize: 12 }} onClick={() => setMode(isLogin ? 'signup' : 'login')}>{isLogin ? 'Create a free account →' : 'Log in instead →'}</button>
              </div>

              <p className="mono-plain" style={{ margin: '18px 0 0' }}>NO CARD · NO AUTO-POSTING · EVER</p>
            </form>

          </div>

          <div className="auth-visual slab">

            <div id="visual-login" className="auth-visual__panel" hidden={!isLogin}>
              <div className="auth-visual__row">
                <span className="mono" style={{ color: 'var(--lime)' }}>Sample run · what you get</span>
                <span className="mono-plain" style={{ color: 'var(--on-dark-dim)' }}>deno/workspace</span>
              </div>
              <div className="auth-visual__verdict">
                <div className="display" style={{ fontSize: 'clamp(44px,5.6vw,68px)', color: 'var(--lime)' }}>PIVOT</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 10 }}>
                  <span className="display" style={{ fontSize: 28 }}>65%</span>
                  <span className="mono-plain" style={{ color: 'var(--on-dark-dim)' }}>Confidence from evidence</span>
                </div>
                <p style={{ margin: '12px 0 0', fontSize: 14, lineHeight: 1.55, color: 'var(--on-dark-soft)' }}>Example: churn prediction for small SaaS. 89 posts read, 21 claims verified, 12 competitor mentions.</p>
              </div>
              <div className="auth-visual__list">
                <div><span className="mono" style={{ color: 'var(--lime)' }}>30-day plan</span><span>Day 06 draft ready to send</span><span className="mono-plain">Ban risk 91</span></div>
                <div><span className="mono" style={{ color: 'var(--lime)' }}>Story bank</span><span>14 entries · 6 metrics on file</span><span className="mono-plain">Synced</span></div>
                <div><span className="mono" style={{ color: 'var(--lime)' }}>Automated</span><span>Actions taken while you were away</span><span className="mono-plain">0</span></div>
              </div>
              <div className="auth-visual__shot">
                <div className="auth-visual__shot-head">
                  <span>WORKSPACE · 01 INTAKE</span><span style={{ color: 'var(--on-dark-dim)' }}>EXAMPLE</span>
                </div>
                <img src="/assets/workspace-intake.png" alt="Deno workspace intake screen" />
              </div>
            </div>

            <div id="visual-signup" className="auth-visual__panel" hidden={isLogin}>
              <span className="mono" style={{ color: 'var(--lime)' }}>What the free account includes</span>
              <div className="display" style={{ fontSize: 'clamp(26px,3vw,40px)', lineHeight: 1.04 }}>Free during the beta. No card.</div>
              <div className="auth-visual__features">
                <div><span className="mono" style={{ color: 'var(--lime)' }}>01</span><span>Five validations a month <span style={{ color: 'var(--on-dark-dim)' }}>— one of the agents is a critic by design.</span></span></div>
                <div><span className="mono" style={{ color: 'var(--lime)' }}>02</span><span>Build / Pivot / Kill verdict <span style={{ color: 'var(--on-dark-dim)' }}>— or &ldquo;not enough evidence&rdquo; when that&apos;s the truth.</span></span></div>
                <div><span className="mono" style={{ color: 'var(--lime)' }}>03</span><span>Real posts from Reddit, HN, X and Product Hunt <span style={{ color: 'var(--on-dark-dim)' }}>— each one linked.</span></span></div>
                <div><span className="mono" style={{ color: 'var(--lime)' }}>04</span><span>Source ledger <span style={{ color: 'var(--on-dark-dim)' }}>— claims that fail verification are dropped, never guessed.</span></span></div>
                <div className="auth-visual__features-dim"><span className="mono">05</span><span>Ban Risk Score, content calendar and Story Bank — included during the beta.</span></div>
              </div>
              <div className="auth-visual__cta">
                <span className="display" style={{ fontSize: 22, lineHeight: 1.1 }}>Find out tonight.<br />Post on Monday.</span>
                <span className="mono">~3–6 MIN<br />RUNTIME</span>
              </div>
            </div>

          </div>

        </div>

      </div>
    </div>
  );
}
