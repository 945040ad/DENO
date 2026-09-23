import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { FontLinks } from '@/components/FontLinks';
import '@/styles/base.css';
import '@/styles/landing.css';

export const metadata: Metadata = {
  title: "Deno — Know if it's worth building, then get your first 100 users",
  description:
    'Eight adversarial agents stress-test your startup idea against real sources. Then Deno writes thirty days of posts in your own voice — every one scored for ban risk before you send.',
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
