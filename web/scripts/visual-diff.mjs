/**
 * Pixel-parity check: screenshots the original static pages (../public, served
 * separately) and the Next.js routes at several widths and diffs them.
 *
 *   ORIGINAL_URL=http://127.0.0.1:8088 NEXT_URL=http://127.0.0.1:3100 npm run test:visual
 *
 * CHROMIUM_PATH can point at an already-installed Chromium binary.
 * Diff images for any mismatch land in ./visual-diff/. Exits 1 on any diff.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import pixelmatch from 'pixelmatch';
import { chromium } from 'playwright';
import { PNG } from 'pngjs';

const ORIGINAL = process.env.ORIGINAL_URL ?? 'http://127.0.0.1:8088';
const NEXT = process.env.NEXT_URL ?? 'http://127.0.0.1:3100';
const WIDTHS = (process.env.WIDTHS ?? '1440,1024,390').split(',').map(Number);
const OUT = 'visual-diff';

const PAGES = [
  { name: 'landing', original: '/index.html', next: '/' },
  { name: 'auth-login', original: '/auth.html', next: '/auth' },
  { name: 'auth-signup', original: '/auth.html?mode=signup', next: '/auth?mode=signup' },
  { name: 'workspace', original: '/app.html', next: '/app' },
];

async function shoot(browser, url, width) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => Promise.all([...document.images].map((img) => img.decode().catch(() => {}))));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  const buf = await page.screenshot({ fullPage: true, animations: 'disabled', caret: 'hide' });
  await context.close();
  return PNG.sync.read(buf);
}

function crop(png, width, height) {
  const out = new PNG({ width, height });
  PNG.bitblt(png, out, 0, 0, width, height, 0, 0);
  return out;
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
mkdirSync(OUT, { recursive: true });
let failures = 0;

for (const p of PAGES) {
  for (const width of WIDTHS) {
    const a = await shoot(browser, ORIGINAL + p.original, width);
    const b = await shoot(browser, NEXT + p.next, width);
    const w = Math.min(a.width, b.width);
    const h = Math.min(a.height, b.height);
    const diff = new PNG({ width: w, height: h });
    const pixels = pixelmatch(crop(a, w, h).data, crop(b, w, h).data, diff.data, w, h, { threshold: 0 });
    const sizeNote = a.height === b.height && a.width === b.width ? '' : ` size ${a.width}x${a.height} vs ${b.width}x${b.height}`;
    const ok = pixels === 0 && !sizeNote;
    console.log(`${ok ? 'PASS' : 'FAIL'} ${p.name}@${width}: ${pixels} px differ${sizeNote}`);
    if (!ok) {
      failures++;
      const base = `${OUT}/${p.name}-${width}`;
      writeFileSync(`${base}-diff.png`, PNG.sync.write(diff));
      writeFileSync(`${base}-original.png`, PNG.sync.write(a));
      writeFileSync(`${base}-next.png`, PNG.sync.write(b));
    }
  }
}

await browser.close();
process.exit(failures ? 1 : 0);
