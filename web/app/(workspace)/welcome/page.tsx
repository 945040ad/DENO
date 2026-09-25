import { SystemShell } from '@/components/pages/SystemShell';

export const metadata = { title: 'Deno — Email confirmed' };

export default function Welcome() {
  return (
    <SystemShell>
      <div className="dv-rise" style={{ padding: 'clamp(32px,6vw,96px) clamp(24px,3.4vw,52px)', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 18, maxWidth: 820 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--green)' }}>
          <span className="dv-dot" />
          <span className="dv-mono" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: '.1em' }}>EMAIL CONFIRMED</span>
        </div>
        <h1 className="dv-h1 xl">You&apos;re in. Bring the idea you&apos;ve been sitting on.</h1>
        <p className="dv-lede" style={{ fontSize: 16 }}>Describe it in a sentence or two. Agents read what real people post about the problem, check every claim against its source, and hand you a verdict you can click through.</p>
        <a href="/app" className="dv-btn lime" style={{ fontSize: 16, padding: '16px 24px' }}>Start my first run →</a>
      </div>
    </SystemShell>
  );
}
