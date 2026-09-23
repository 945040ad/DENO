import { NextResponse, type NextRequest } from 'next/server';
import { safeNext } from '@/lib/supabase/config';
import { createClient } from '@/lib/supabase/server';

/**
 * PKCE landing point for OAuth sign-in, sign-up confirmation and password
 * reset links (Supabase's default email templates redirect here with ?code=).
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get('code');
  const next = safeNext(searchParams.get('next'));
  const providerError = searchParams.get('error_description');

  if (code) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) return NextResponse.redirect(`${origin}${next}`);
    }
  }

  const message = providerError ?? 'That sign-in link is invalid or has expired. Try again.';
  return NextResponse.redirect(`${origin}/auth?error=${encodeURIComponent(message)}`);
}
