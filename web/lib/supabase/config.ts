/**
 * Supabase project settings, read from the public env vars.
 *
 * When they are missing (fresh checkout, no project wired up yet) auth is
 * treated as disabled: the workspace is reachable without a session and the
 * auth screen shows its dev "skip login" strip. Setting both vars turns
 * enforcement on everywhere — there is no separate flag to forget.
 */
export interface SupabaseConfig {
  url: string;
  publishableKey: string;
}

export function getSupabaseConfig(): SupabaseConfig | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !publishableKey) return null;
  return { url, publishableKey };
}

export function isAuthEnabled(): boolean {
  return getSupabaseConfig() !== null;
}

/**
 * "Keep me signed in" unchecked → the auth cookies are written as session
 * cookies (no Max-Age) so they die with the browser. The choice itself lives
 * in a session cookie so server-side refreshes (proxy.ts) keep honouring it.
 */
export const REMEMBER_COOKIE = 'deno-remember';

interface CookieLifetime {
  maxAge?: number;
  expires?: Date;
}

/**
 * @supabase/ssr always writes auth cookies with a 400-day Max-Age and ignores
 * a maxAge passed in cookieOptions, so the lifetime is adjusted in setAll.
 * Deletions (maxAge 0) pass through untouched.
 */
export function applyRemember<T extends CookieLifetime>(options: T, remember: boolean): T {
  if (remember || options.maxAge === 0) return options;
  const sessionOnly = { ...options };
  delete sessionOnly.maxAge;
  delete sessionOnly.expires;
  return sessionOnly;
}

/** Only allow same-origin relative redirect targets (blocks open redirects). */
export function safeNext(next: string | null | undefined, fallback = '/app'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback;
  return next;
}
