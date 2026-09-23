import { createBrowserClient, parseCookieHeader, serializeCookieHeader } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { REMEMBER_COOKIE, applyRemember, getSupabaseConfig } from './config';

function rememberFromDocument(): boolean {
  return !document.cookie.split('; ').includes(`${REMEMBER_COOKIE}=0`);
}

/** Browser Supabase client, or null when the project isn't configured. */
export function createClient(): SupabaseClient | null {
  const config = getSupabaseConfig();
  if (!config) return null;
  return createBrowserClient(config.url, config.publishableKey, {
    cookies: {
      getAll() {
        return parseCookieHeader(document.cookie).map(({ name, value }) => ({ name, value: value ?? '' }));
      },
      setAll(cookiesToSet) {
        const remember = rememberFromDocument();
        cookiesToSet.forEach(({ name, value, options }) => {
          document.cookie = serializeCookieHeader(name, value, applyRemember(options, remember));
        });
      },
    },
  });
}

/** Persist the "Keep me signed in" choice before signing in. */
export function setRememberPreference(remember: boolean): void {
  // Session cookie on purpose: with "remember" off, the preference must die
  // with the browser together with the auth cookies it governs.
  document.cookie = remember
    ? `${REMEMBER_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
    : `${REMEMBER_COOKIE}=0; Path=/; SameSite=Lax`;
}
