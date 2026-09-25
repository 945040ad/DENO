import { SystemShell } from '@/components/pages/SystemShell';
import { TakedownForm } from '@/components/pages/TakedownForm';

export const metadata = { title: 'Deno — Remove your content' };

export default function Takedown() {
  return (
    <SystemShell>
      <TakedownForm />
    </SystemShell>
  );
}
