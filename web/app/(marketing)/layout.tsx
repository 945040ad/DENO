import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { FontLinks } from '@/components/FontLinks';
import '@/styles/base.css';
import '@/styles/landing.css';

export const metadata: Metadata = {
  title: "Deno — Know if it's worth building, then get your first 100 users",
  description:
    'Deno checks your startup idea against real Reddit, Hacker News, X and Product Hunt posts, with every claim linked to its source. Then it drafts up to thirty days of posts in your voice, each one checked before you send.',
};

export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
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
