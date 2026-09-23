import { redirect } from 'next/navigation';
import { Workspace } from '@/components/workspace/Workspace';
import { isAuthEnabled } from '@/lib/supabase/config';
import { getUserId } from '@/lib/supabase/server';

// Depends on the request's auth cookies; never prerender.
export const dynamic = 'force-dynamic';

export default async function WorkspacePage() {
  // proxy.ts already redirects signed-out users; this is the authoritative check.
  if (isAuthEnabled() && !(await getUserId())) redirect('/auth?next=/app');
  return <Workspace />;
}
