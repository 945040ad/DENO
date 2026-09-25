import { SystemShell } from '@/components/pages/SystemShell';

export default function NotFound() {
  return (
    <SystemShell>
      <div className="dv-split wide dv-rise">
        <div className="dv-pad lg dv-rr" style={{ padding: 'clamp(28px,5vw,72px)' }}>
          <span className="dv-kicker ink">VERDICT · 404</span>
          <div className="dv-serif" style={{ fontSize: 'clamp(80px,12vw,168px)', lineHeight: 0.85, color: 'var(--red-ink)', margin: '22px 0 10px' }}>KILL</div>
          <p className="dv-lede" style={{ fontSize: 16, marginBottom: 22, maxWidth: 440 }}>This page doesn&apos;t exist. We checked, and we don&apos;t guess.</p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <a href="/app" className="dv-btn lime">Pivot to workspace →</a>
            <a href="/" className="dv-btn ghost">Home</a>
          </div>
        </div>
        <div className="dv-pad lg dv-dark" style={{ padding: 'clamp(28px,5vw,72px)', display: 'flex', flexDirection: 'column', gap: 8, justifyContent: 'center' }}>
          <span className="dv-dark-label" style={{ marginBottom: 8 }}>TOP ARGUMENTS</span>
          {['No page at this address', 'No matching route in the workspace', 'Unsourced pages are dropped, never guessed'].map((t) => (
            <div key={t} className="dv-row" style={{ fontSize: 14 }}>{t}</div>
          ))}
        </div>
      </div>
    </SystemShell>
  );
}
