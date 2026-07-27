/*
 * When you reach the bottom, there has to be something there.
 *
 * The contract is in docs/architecture.md: the Mini App is a screen, not a
 * document. The bug this guards against is not "the page scrolls" — a list is
 * supposed to — it is travel that reveals nothing, which reads as a broken
 * screen and is invisible on a desktop window.
 *
 * "A screen that fits must not scroll" was the obvious rule and it is the
 * wrong one. For any layout there is a band of viewport heights where the
 * content is a handful of pixels too tall, so a threshold on travel only moves
 * the failing size around; it says nothing about whether the travel was
 * pointless. What separates the bug from an ordinary short list is what is
 * waiting at the end of the scroll.
 *
 * So: scroll to the bottom, then ask where the lowest content sits. It should
 * be against the bottom edge — above the tab bar where there is one, a
 * screen's padding above the edge where there is not. Anything more is dead
 * space that was scrolled through for nothing.
 *
 * Measured at several viewport sizes, because a screen that fits on a tall
 * phone is not the question.
 *
 * Needs the dev server (`make web`) with the API behind it: an empty state and
 * a failed request are different heights, so a screen measured against a dead
 * API proves nothing. Both are checked rather than assumed — a blank page has
 * nothing to scroll either, and that is the one way a check like this could
 * congratulate itself on a screen that never came up.
 *
 * `make web` serves https through mkcert, which needs sudo once. Where it
 * cannot have it, run the server with VITE_NO_HTTPS=1 and pass
 * BASE=http://localhost:5173.
 */

import { chromium } from 'playwright';

const BASE = process.env.BASE || 'https://localhost:5173';

/** Real phones. The short ones are where the last few pixels appear. */
const VIEWPORTS = [
  { width: 390, height: 664 },
  { width: 360, height: 640 },
  { width: 390, height: 568 },
];

const ROUTES = [
  '/',
  '/ask',
  '/results',
  '/mine',
  '/life',
  '/profile',
  '/become-helper',
  '/my-helper',
  '/nope',
];

/**
 * How much emptiness under the last row is by design.
 *
 * A screen keeps 16px clear at its foot — see `.screen` in ui.module.css,
 * which is the one place that number lives — and a few pixels of rounding sit
 * on top of that. Past this, the space is not clearance, it is a spacer nobody
 * meant to leave.
 */
const BY_DESIGN = 20;

const browser = await chromium.launch();
const failures = [];

/** Stop before measuring anything if the thing being measured is not there. */
async function preflight() {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  try {
    const health = await page.goto(`${BASE}/healthz`, { timeout: 15000 });
    if (!health?.ok()) throw new Error(`/healthz answered ${health?.status()}`);
    const body = await page.evaluate(() => document.body.innerText);
    if (!body.includes('"database":"ok"')) {
      throw new Error(`/healthz says ${body.trim().slice(0, 120)}`);
    }
  } catch (error) {
    console.error(`Cannot measure against ${BASE}: ${error.message}`);
    console.error('Start the dev server (make web) and the API (make api) first,');
    console.error('or point BASE at a running one.');
    await browser.close();
    process.exit(2);
  }
  await context.close();
}

/**
 * Everything the page has to say about its own bottom edge.
 *
 * Runs in the browser twice — before and after scrolling — because the
 * question is what the scroll changed.
 */
function look() {
  /**
   * Does this element put anything on the screen?
   *
   * A spacer is an element with a height and nothing in it, and it is exactly
   * what this check exists to find. Counting it as content would let the
   * scroll end "on" it and report the screen as fine — which is how the
   * 24-pixel block at the foot of /life stayed invisible.
   */
  function paints(el) {
    if (el.childElementCount > 0 || el.textContent.trim()) return true;
    const style = getComputedStyle(el);
    const filled =
      style.backgroundImage !== 'none' ||
      !['transparent', 'rgba(0, 0, 0, 0)'].includes(style.backgroundColor);
    const bordered =
      ['Top', 'Right', 'Bottom', 'Left'].some(
        (side) => Number.parseFloat(style[`border${side}Width`]) > 0,
      ) || style.boxShadow !== 'none';
    return filled || bordered;
  }

  const doc = document.documentElement;
  const root = document.getElementById('root');
  if (!root?.firstElementChild) return { rendered: false };

  // The tab bar is fixed and overlays the foot of the screen, so the content
  // it covers is not visible content and its own bottom edge is not the
  // page's. Same for the sheet and its scrim when one is open.
  const floating = new Set();
  for (const el of root.querySelectorAll('*')) {
    if (getComputedStyle(el).position === 'fixed') {
      floating.add(el);
      for (const child of el.querySelectorAll('*')) floating.add(child);
    }
  }

  let lowest = Number.NEGATIVE_INFINITY;
  let cover = 0;
  for (const el of root.querySelectorAll('*')) {
    const box = el.getBoundingClientRect();
    if (box.height <= 0 || box.width <= 0) continue;
    if (floating.has(el)) {
      if (box.bottom >= window.innerHeight - 1) {
        cover = Math.max(cover, box.height);
      }
      continue;
    }
    // The screen itself is skipped: its bottom edge is its own reserve for
    // the tab bar, which is the very padding this check is trying to look
    // past. Everything inside it counts, cards and their padding included —
    // a card's own foot is part of the card.
    if (el.parentElement === root) continue;
    if (!paints(el)) continue;
    lowest = Math.max(lowest, box.bottom);
  }

  return {
    rendered: true,
    travel: doc.scrollHeight - doc.clientHeight + (root.scrollHeight - root.clientHeight),
    // How far the lowest content sits above the lowest place it could be.
    slack: window.innerHeight - cover - lowest,
  };
}

await preflight();

for (const viewport of VIEWPORTS) {
  const label = `${viewport.width}x${viewport.height}`;
  // mkcert's certificate is not in this process's trust store, and a TLS error
  // here would otherwise look exactly like a screen that fits.
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    ignoreHTTPSErrors: true,
  });

  console.log(`\n${label}`);
  for (const route of ROUTES) {
    const page = await context.newPage();
    try {
      const response = await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' });
      if (response && !response.ok()) throw new Error(`HTTP ${response.status()}`);
    } catch (error) {
      console.error(`\nCannot reach ${BASE}${route}: ${error.message}`);
      await browser.close();
      process.exit(2);
    }
    await page.waitForTimeout(900);
    // The development console is a floating panel of its own and would
    // otherwise count as content.
    await page.addStyleTag({ content: '#eruda{display:none !important}' });
    await page.waitForTimeout(100);

    const before = await page.evaluate(look);
    if (!before.rendered) {
      console.error(`\n${route} rendered nothing at ${label}.`);
      await browser.close();
      process.exit(2);
    }

    // To the end of whichever box turns out to be the scrolling one.
    await page.evaluate(() => {
      const root = document.getElementById('root');
      if (root) root.scrollTop = root.scrollHeight;
      document.documentElement.scrollTop = document.documentElement.scrollHeight;
    });
    await page.waitForTimeout(200);
    const after = await page.evaluate(look);
    await page.close();

    const dead = before.travel > 0 ? Math.round(after.slack) : 0;
    const pointless = dead > BY_DESIGN;
    console.log(
      `  ${pointless ? 'FAIL' : 'ok  '} ${route.padEnd(16)}` +
        ` travel=${Math.round(before.travel)}px  empty at the end=${dead}px`,
    );
    if (pointless) failures.push(`${route} at ${label}: ${dead}px of nothing`);
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(
    `\n${failures.length} screen(s) scroll to nothing:\n  ${failures.join('\n  ')}`,
  );
  process.exit(1);
}
console.log(`\nEvery scroll ends on content, at all ${VIEWPORTS.length} sizes.`);
