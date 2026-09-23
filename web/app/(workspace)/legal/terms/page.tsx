import { SimpleShell } from '@/components/pages/SimpleShell';

export const metadata = { title: 'Deno — Terms' };

export default function Terms() {
  return (
    <SimpleShell>
      <div className="section-title">
        <h2>Terms</h2>
        <p>The short version. Last updated September 2026.</p>
      </div>
      <div className="card prose">
        <h3>What Deno is</h3>
        <p>Deno summarises what people publicly say about a problem, with links to every post it relies on. It is research help, not financial or legal advice. A verdict can be wrong; read the sources before you bet on it.</p>
        <h3>Drafts</h3>
        <p>Deno writes drafts for you to review. It never posts for you. You are responsible for what you publish and for following each community&apos;s rules.</p>
        <h3>Fair use</h3>
        <p>Don&apos;t use Deno to harass people, to scrape at scale, or to publish content that pretends to be someone else. We may suspend accounts that do.</p>
        <h3>Plans</h3>
        <p>Paid plans renew monthly until you cancel in the billing portal. If a payment fails, your account moves to the Free plan and your data stays.</p>
        <h3>Contact</h3>
        <p>Questions or content removal: use the <a href="/takedown">takedown page</a>.</p>
      </div>
    </SimpleShell>
  );
}
