import type { EmailOtpType } from '@supabase/supabase-js';
import { NextResponse, type NextRequest } from 'next/server';
import { safeNext } from '@/lib/supabase/config';
import { createClient } from '@/lib/supabase/server';

/**
 * Token-hash email links, for projects whose email templates point at
 * `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=...` (works
 * across browsers, unlike PKCE links, which need the original tab's verifier).
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const tokenHash = searchParams.get('token_hash');
  const type = searchParams.get('type') as EmailOtpType | null;
  const next = type === 'recovery' ? '/auth/reset' : safeNext(searchParams.get('next'));

  if (tokenHash && type) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
      if (!error) return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(
    `${origin}/auth?error=${encodeURIComponent('That confirmation link is invalid or has expired. Try again.')}`,
  );
}
