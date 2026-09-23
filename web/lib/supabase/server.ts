import { createServerClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import { REMEMBER_COOKIE, applyRemember, getSupabaseConfig } from './config';

/**
 * Server Supabase client for server components, route handlers and server
 * actions. Returns null when the project isn't configured.
 */
export async function createClient(): Promise<SupabaseClient | null> {
  const config = getSupabaseConfig();
  if (!config) return null;
  const cookieStore = await cookies();
  const remember = cookieStore.get(REMEMBER_COOKIE)?.value !== '0';

  return createServerClient(config.url, config.publishableKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, applyRemember(options, remember)));
        } catch {
          // Called from a server component, where cookies are read-only.
          // proxy.ts refreshes the session, so this is safe to ignore.
        }
      },
    },
  });
}

/** Verified user id from the access token (getClaims checks the JWT signature). */
export async function getUserId(): Promise<string | null> {
  const supabase = await createClient();
  if (!supabase) return null;
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims?.sub) return null;
  return data.claims.sub;
}
