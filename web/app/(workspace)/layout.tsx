import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { FontLinks } from '@/components/FontLinks';
import '@/styles/base.css';
import '@/styles/app.css';
import '@/styles/dv.css';

export const metadata: Metadata = {
  title: 'Deno — Workspace',
  description:
    'Grounded startup idea validation, 30-day voice-matched content calendar, and real-time Ban Risk scoring.',
};

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  // Reading the request makes the page dynamic, so every response gets a fresh CSP nonce.
  await headers();
  return (
    <html lang="en">
      <head>
        <FontLinks />
      </head>
      <body>{children}</body>
    </html>
  );
}
