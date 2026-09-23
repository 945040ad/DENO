import type { AuthMode } from './AuthScreen';

export function AuthTopbar({ mode, onMode }: { mode: AuthMode | null; onMode: (mode: AuthMode) => void }) {
  return (
    <div className="auth-topbar">
      <a href="/" className="brand brand--sm">
        <span className="brand__word">deno</span>
        <span className="brand__chip">GTM</span>
      </a>
      <div className="auth-topbar__switch">
        <button type="button" className={`auth-topbar__btn${mode === 'login' ? ' is-active' : ''}`} id="tab-login" data-mode="login" onClick={() => onMode('login')}>Log in</button>
        <button type="button" className={`auth-topbar__btn${mode === 'signup' ? ' is-active' : ''}`} id="tab-signup" data-mode="signup" onClick={() => onMode('signup')}>Sign up</button>
      </div>
      <a href="/" className="mono-plain auth-topbar__back">← Back to site</a>
    </div>
  );
}
