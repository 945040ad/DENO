import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { FontLinks } from '@/components/FontLinks';
import '@/styles/base.css';
import '@/styles/auth.css';

export const metadata: Metadata = {
  title: 'Deno — Log in or create a free account',
  description:
    'Log in to pick up your last verdict, or create a free account and validate your first idea in ninety seconds.',
};

export default async function AuthLayout({ children }: { children: React.ReactNode }) {
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
