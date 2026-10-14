'use client';

import { useEffect, useRef, useState } from 'react';
import { createClient } from '@/lib/supabase/client';

export function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [signedIn, setSignedIn] = useState(false);

  // Read the local session (no network call) so a signed-in visitor gets a way back to the workspace.
  useEffect(() => {
    const supabase = createClient();
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSignedIn(Boolean(data.session))).catch(() => undefined);
    const { data } = supabase.auth.onAuthStateChange((_event, session) => setSignedIn(Boolean(session)));
    return () => data.subscription.unsubscribe();
  }, []);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuRef.current?.contains(target) || toggleRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setMenuOpen(false);
      toggleRef.current?.focus();
    };
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  return (
    <header className="site-header" id="top">
      <div className="site-header__row">
        <a href="#top" className="brand">
          <span className="brand__word">deno</span>
          <span className="brand__chip">GTM</span>
        </a>

        <nav className="site-nav">
          <button
            type="button"
            className="site-nav__link site-nav__menu-btn"
            id="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="mega-menu"
            ref={toggleRef}
            onClick={() => setMenuOpen((open) => !open)}
          >
            Platform <span className="site-nav__chevron">▼</span>
          </button>
          <a href="#how" className="site-nav__link">How it works</a>
          <a href="#risk" className="site-nav__link">Ban Risk</a>
          <a href="#receipts" className="site-nav__link">Receipts</a>
          <a href="#pricing" className="site-nav__link">Pricing</a>
        </nav>

        <div className="site-header__actions">
          {signedIn ? (
            <>
              <a href="/app/account" className="site-header__login">Account</a>
              <a href="/app" className="btn btn--lime btn--raised">Open dashboard →</a>
            </>
          ) : (
            <>
              <a href="/auth" className="site-header__login">Log in</a>
              <a href="/auth?mode=signup" className="btn btn--lime btn--raised">Validate an idea</a>
            </>
          )}
        </div>
      </div>

      <div className="mega-menu" id="mega-menu" hidden={!menuOpen} ref={menuRef}>
        <div className="mega-menu__grid">
          <div className="mega-menu__col">
            <div className="mega-menu__swatch grid-wash grid-wash--green"></div>
            <div className="display" style={{ fontSize: 24, marginBottom: 6 }}>Validation</div>
            <div className="mega-menu__desc">Research agents and a critic. One Build / Pivot / Kill verdict, with sources.</div>
            <div className="mega-menu__links">
              <a href="/app">Idea intake →</a><a href="#how">Market sizing →</a><a href="#how">Source ledger →</a>
            </div>
          </div>
          <div className="mega-menu__col">
            <div className="mega-menu__swatch grid-wash grid-wash--peach"></div>
            <div className="display" style={{ fontSize: 24, marginBottom: 6 }}>Distribution</div>
            <div className="mega-menu__desc">Up to thirty days of posts in your voice, for the communities that will have you.</div>
            <div className="mega-menu__links">
              <a href="/app">Content calendar →</a><a href="#how">Community radar →</a><a href="#how">Hook library →</a>
            </div>
          </div>
          <div className="mega-menu__col">
            <div className="mega-menu__swatch grid-wash grid-wash--blue"></div>
            <div className="display" style={{ fontSize: 24, marginBottom: 6 }}>Ban Risk</div>
            <div className="mega-menu__desc">A 0–100 score on every draft, with the exact line that will get you filtered.</div>
            <div className="mega-menu__links">
              <a href="#risk">Anti-slop scrubber →</a><a href="#risk">Density scorer →</a><a href="#risk">Rule conflicts →</a>
            </div>
          </div>
          <div className="mega-menu__feature">
            <span className="tag tag--lime" style={{ marginBottom: 12 }}>Story Bank</span>
            <div className="display" style={{ fontSize: 22, lineHeight: 1.15, marginBottom: 8 }}>Your scars are the moat</div>
            <div className="mega-menu__desc" style={{ marginBottom: 14 }}>Receipts, metrics and failures no model can invent — injected into every post.</div>
            <a href="/app" className="link-mono">Open Story Bank →</a>
          </div>
        </div>
      </div>
    </header>
  );
}
