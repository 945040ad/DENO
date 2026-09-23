import type { ReactNode } from 'react';

/** Workspace chrome for standalone pages (account, legal, takedown), same classes as the workspace. */
export function SimpleShell({ children }: { children: ReactNode }) {
  return (
    <div className="workspace-shell">
      <div className="workspace-frame">
        <header className="workspace-topbar">
          <a href="/" className="brand brand--sm">
            <span className="brand__word">deno</span>
            <span className="brand__chip">GTM</span>
          </a>
          <nav className="nav-tabs">
            <a className="nav-tab" href="/app">Workspace</a>
            <a className="nav-tab" href="/app/account">Account</a>
            <a className="nav-tab" href="/legal/privacy">Privacy</a>
            <a className="nav-tab" href="/legal/terms">Terms</a>
          </nav>
        </header>
        <main className="main-content">
          <section className="tab-pane active">{children}</section>
        </main>
      </div>
    </div>
  );
}
