import { AuthScreen, type AuthMode } from '@/components/auth/AuthScreen';
import { isAuthEnabled, safeNext } from '@/lib/supabase/config';

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AuthPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const mode: AuthMode = first(params.mode) === 'signup' ? 'signup' : 'login';
  return (
    <AuthScreen
      initialMode={mode}
      next={safeNext(first(params.next))}
      initialError={first(params.error) ?? null}
      authEnabled={isAuthEnabled()}
    />
  );
}
