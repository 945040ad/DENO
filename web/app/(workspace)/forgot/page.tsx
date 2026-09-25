import { ForgotPassword } from '@/components/pages/ForgotPassword';
import { SystemShell } from '@/components/pages/SystemShell';

export const metadata = { title: 'Deno — Reset your password' };

export default function Forgot() {
  return (
    <SystemShell back={{ href: '/auth', label: '← BACK TO LOG IN' }}>
      <ForgotPassword />
    </SystemShell>
  );
}
