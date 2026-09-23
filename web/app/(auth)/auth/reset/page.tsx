import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { ResetPassword } from '@/components/auth/ResetPassword';
import { getUserId } from '@/lib/supabase/server';

// Depends on the request's auth cookies; never prerender.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Deno — Set a new password' };

export default async function ResetPage() {
  // The recovery link signs the user in; without that session there is nothing to reset.
  if (!(await getUserId())) {
    redirect(`/auth?error=${encodeURIComponent('Open the reset link from your email to set a new password.')}`);
  }
  return <ResetPassword />;
}
