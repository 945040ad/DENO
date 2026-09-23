import type { NextConfig } from 'next';

const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  ...(process.env.NODE_ENV === 'production'
    ? [{ key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' }]
    : []),
];

const nextConfig: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  // Next's gzip/brotli buffers proxied text/event-stream responses (run progress never arrives).
  // Caddy compresses everything else in production.
  compress: false,
  // The FastAPI backend stays the source of truth for /api/*; Next.js is the BFF
  // in front of it (replaces the Deno gateway).
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
