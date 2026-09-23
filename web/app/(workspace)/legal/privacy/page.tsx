import { SimpleShell } from '@/components/pages/SimpleShell';

export const metadata = { title: 'Deno — Privacy' };

export default function Privacy() {
  return (
    <SimpleShell>
      <div className="section-title">
        <h2>Privacy</h2>
        <p>Plain-language summary of what Deno stores and why. Last updated September 2026.</p>
      </div>
      <div className="card prose">
        <h3>Your account</h3>
        <p>We store your email (through Supabase Auth), your ideas, validation reports, voice samples, Story Bank entries and drafts. They are visible only to you. We never sell them or use them to train models.</p>
        <h3>Public posts we read</h3>
        <p>When you run a validation, Deno fetches public posts (Reddit via Arctic Shift, Hacker News, X, Product Hunt and others) that match your idea. We only fetch when you start a run, never by crawling. The text of those posts is deleted after 90 days; we keep the link so your report&apos;s citations still work. Anyone can ask us to remove their posts on the <a href="/takedown">takedown page</a>.</p>
        <h3>AI providers</h3>
        <p>Your idea and the retrieved posts are sent to NVIDIA&apos;s hosted models to analyse them. We don&apos;t send your email or payment details.</p>
        <h3>Payments</h3>
        <p>Stripe handles payments. We never see or store your card.</p>
        <h3>Your rights</h3>
        <p>You can download all your data or delete your account at any time from <a href="/app/account">Account</a>. Deletion is immediate and permanent.</p>
      </div>
    </SimpleShell>
  );
}
