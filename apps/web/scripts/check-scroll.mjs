/*
 * A screen that fits must not scroll.
 *
 * The contract is in docs/architecture.md: the Mini App is a screen, not a
 * document, and the few pixels of travel a screen with nothing on it used to
 * offer are a layout bug rather than a rounding error. This is that check,
 * because the bug is invisible on a desktop window and obvious on a phone.
 *
 * Travel is measured as the document's overflow plus #root's, added together
 * on purpose: which of the two boxes scrolls is an implementation detail, and
 * a check that watched only one would go quiet the moment the overflow moved.
 *
 * The routes below are the ones that hold a screenful at most. A list screen
 * is expected to scroll and is not listed; it is not that its travel is fine,
 * it is that the right number for it is "however long the list is".
 *
 * Needs the dev server (`make web`) and the API behind it, because an empty
 * state and a failed request are different heights. Run it as
 * `pnpm check:scroll`, or against another origin with BASE=…
 */

import { chromium } from 'playwright';

const BASE = process.env.BASE || 'http://localhost:5173';

/** A small phone in Telegram, which is where the pixels are tightest. */
const VIEWPORT = { width: 390, height: 664 };

const SHORT_SCREENS = ['/', '/ask', '/mine', '/life', '/profile', '/become-helper'];

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: VIEWPORT,
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});

const failures = [];

for (const route of SHORT_SCREENS) {
  const page = await context.newPage();
  await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' }).catch(() => {});
  await page.waitForTimeout(900);
  // The development console is a floating panel of its own and would otherwise
  // count as content.
  await page.addStyleTag({ content: '#eruda{display:none !important}' });
  await page.waitForTimeout(100);

  const travel = await page.evaluate(() => {
    const doc = document.documentElement;
    const root = document.getElementById('root');
    return (
      doc.scrollHeight -
      doc.clientHeight +
      (root ? root.scrollHeight - root.clientHeight : 0)
    );
  });

  console.log(`${travel === 0 ? 'ok  ' : 'FAIL'} ${route.padEnd(16)} travel=${travel}px`);
  if (travel !== 0) failures.push(`${route}: ${travel}px`);
  await page.close();
}

await browser.close();

if (failures.length) {
  console.error(
    `\n${failures.length} screen(s) scroll with nothing to scroll to:\n  ${failures.join('\n  ')}`,
  );
  process.exit(1);
}
console.log(
  `\nAll ${SHORT_SCREENS.length} screens fit at ${VIEWPORT.width}x${VIEWPORT.height}.`,
);
