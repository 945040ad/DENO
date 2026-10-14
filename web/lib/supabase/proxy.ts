import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import { REMEMBER_COOKIE, applyRemember, getSupabaseConfig, safeNext } from './config';

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
  const isProtected = PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  if (!signedIn && isProtected) return redirectTo(request, response, '/auth', pathname);

  // Already signed in: the log-in / sign-up screen (and every "Validate an idea" link to it) goes
  // straight to the workspace. Sub-routes (/auth/callback, /auth/mfa, /auth/reset…) are untouched.
  if (signedIn && pathname === '/auth') {
    const url = request.nextUrl.clone();
    url.pathname = safeNext(request.nextUrl.searchParams.get('next'));
    url.search = '';
    const redirect = NextResponse.redirect(url);
    response.cookies.getAll().forEach((c) => redirect.cookies.set(c));
    return redirect;
  }

  if (signedIn && isProtected) {
    // Password-only session on an account with 2FA: ask for the code before the workspace.
    // The API enforces the same rule, so this is the friendly path, not the only guard.
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aal?.nextLevel === 'aal2' && aal.currentLevel !== 'aal2') {
      return redirectTo(request, response, '/auth/mfa', pathname);
    }
  }

  return response;
}

function redirectTo(request: NextRequest, response: NextResponse, path: string, next: string): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = path;
  url.search = '';
  url.searchParams.set('next', next);
  const redirect = NextResponse.redirect(url);
  response.cookies.getAll().forEach((c) => redirect.cookies.set(c));
  return redirect;
}
