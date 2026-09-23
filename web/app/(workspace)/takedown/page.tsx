import { SimpleShell } from '@/components/pages/SimpleShell';
import { TakedownForm } from '@/components/pages/TakedownForm';

export const metadata = { title: 'Deno — Remove your content' };

export default function Takedown() {
  return (
    <SimpleShell>
      <div className="section-title">
        <h2>Remove your posts from Deno</h2>
        <p>Deno reads public posts to help founders research ideas. If something you wrote shows up in a Deno report and you want it gone, tell us here. No account needed.</p>
      </div>
      <TakedownForm />
    </SimpleShell>
  );
}
