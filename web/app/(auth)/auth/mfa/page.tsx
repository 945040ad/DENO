import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { MfaChallenge } from '@/components/auth/MfaChallenge';
import { safeNext } from '@/lib/supabase/config';
import { getUserId } from '@/lib/supabase/server';

// Depends on the request's auth cookies; never prerender.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Deno — Two-factor code' };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function MfaPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const next = safeNext(Array.isArray(params.next) ? params.next[0] : params.next);
  // The code is the second step: without a password session there is nothing to upgrade.
  if (!(await getUserId())) redirect(`/auth?next=${encodeURIComponent(next)}`);
  return <MfaChallenge next={next} />;
}
