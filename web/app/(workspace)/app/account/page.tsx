import { redirect } from 'next/navigation';
import { AccountPage } from '@/components/pages/AccountPage';
import { SimpleShell } from '@/components/pages/SimpleShell';
import { isAuthEnabled } from '@/lib/supabase/config';
import { getUserId } from '@/lib/supabase/server';

export const dynamic = 'force-dynamic';

export default async function Account() {
  if (isAuthEnabled() && !(await getUserId())) redirect('/auth?next=/app/account');
  return (
    <SimpleShell>
      <AccountPage />
    </SimpleShell>
  );
}
