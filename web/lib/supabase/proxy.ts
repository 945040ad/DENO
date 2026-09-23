import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { REMEMBER_COOKIE, applyRemember, getSupabaseConfig } from './config';

/** Paths that need a signed-in user. */
const PROTECTED_PREFIXES = ['/app'];

/**
 * Refreshes the Supabase session on every request and keeps signed-out users
 * out of the workspace. Must return the same response object whose cookies
 * the Supabase client wrote to, or sessions get dropped.
 */
export async function updateSession(request: NextRequest): Promise<NextResponse> {
  let response = NextResponse.next({ request });
  const config = getSupabaseConfig();
  if (!config) return response; // auth not configured → dev mode, nothing to enforce

  const remember = request.cookies.get(REMEMBER_COOKIE)?.value !== '0';
  const supabase = createServerClient(config.url, config.publishableKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet, headers) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, applyRemember(options, remember)));
        Object.entries(headers ?? {}).forEach(([key, value]) => response.headers.set(key, value));
      },
    },
  });

  // Do not put code between createServerClient and getClaims(): it would race
  // the token refresh and randomly log users out.
  const { data } = await supabase.auth.getClaims();
  const signedIn = Boolean(data?.claims?.sub);

  const { pathname } = request.nextUrl;
  if (!signedIn && PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    const url = request.nextUrl.clone();
    url.pathname = '/auth';
    url.search = '';
    url.searchParams.set('next', pathname);
    const redirect = NextResponse.redirect(url);
    response.cookies.getAll().forEach((c) => redirect.cookies.set(c));
    return redirect;
  }

  return response;
}
