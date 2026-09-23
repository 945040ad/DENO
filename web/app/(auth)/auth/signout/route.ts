import { NextResponse, type NextRequest } from 'next/server';
import { createClient } from '@/lib/supabase/server';

/** POST only, so a cross-site <img src> can't log people out. */
export async function POST(request: NextRequest) {
  const supabase = await createClient();
  if (supabase) await supabase.auth.signOut();
  return NextResponse.redirect(new URL('/auth', request.url), { status: 303 });
}
