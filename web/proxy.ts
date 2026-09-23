import type { NextRequest } from 'next/server';
import { buildCsp, newNonce } from '@/lib/csp';
import { updateSession } from '@/lib/supabase/proxy';

export async function proxy(request: NextRequest) {
  const nonce = newNonce();
  const csp = buildCsp(nonce);
  // Request headers let Next.js stamp the nonce on the scripts it renders.
  request.headers.set('x-nonce', nonce);
  request.headers.set('Content-Security-Policy', csp);
  const response = await updateSession(request);
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  // Everything except static assets, prefetches and the /api rewrite to FastAPI
  // (the API authenticates the bearer token itself).
  matcher: [
    {
      source: '/((?!_next/static|_next/image|favicon.ico|assets/|api/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
