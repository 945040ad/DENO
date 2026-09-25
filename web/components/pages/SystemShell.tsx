import type { ReactNode } from 'react';

/** Frame for the system pages (reset, confirmed, takedown, 404): brand left, one way back right. */
export function SystemShell({ children, back = { href: '/', label: '← BACK TO SITE' } }: { children: ReactNode; back?: { href: string; label: string } }) {
  return (
    <div className="dv-shell">
      <div className="dv-frame">
        <div className="dv-top">
          <a href="/" className="dv-brand">
            <span className="dv-brand-word">deno</span>
            <span className="dv-brand-chip">GTM</span>
          </a>
          <a href={back.href} className="dv-back">{back.label}</a>
        </div>
        {children}
      </div>
    </div>
  );
}
