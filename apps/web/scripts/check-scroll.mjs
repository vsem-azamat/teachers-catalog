/*
 * Nothing should be scrollable to a stretch of nothing.
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
 * So the measurement is geometric and needs no scrolling at all: how far is
 * the lowest thing that paints from the bottom of the screen's content box?
 * The screen's own `padding-bottom` is by design and is subtracted, which is
 * also what keeps the number honest on a phone with a home indicator, where
 * that padding includes the inset. Anything left over is dead space.
 *
 * A container does not paint on behalf of its children: a spacer nested inside
 * a card list is the same bug as one at the foot of the screen, and an earlier
 * version of this check — which took any element with children as content —
 * could see the second and not the first.
 *
 * Measured at several viewport sizes, because a screen that fits on a tall
 * phone is not the question.
 *
 * What it cannot do: the mock in `src/mockEnv.ts` reports `tdesktop`, where the
 * SDK synthesises the viewport from `window.innerHeight`, so `--app-height`
 * here is always the same number as the `100dvh` fallback. The iOS and Android
 * path that variable exists for is not exercised by anything on this machine.
 *
 * Needs the dev server (`make web`) and the API behind it, with a signed
 * `VITE_MOCK_INIT_DATA` in `apps/web/.env.local` — the API answers 401 to the
 * unsigned mock, and a screen full of error states is not the screen being
 * measured. All three are checked before anything is measured.
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

/**
 * The detail screens are behind an id this script cannot know, so they are
 * reached the way a person reaches them: by tapping the first row of the list
 * that leads there.
 */
const ROUTES = [
  { path: '/' },
  { path: '/ask' },
  { path: '/results', into: { name: 'helper detail', click: 'button[class*="card"]' } },
  { path: '/mine', into: { name: 'request detail', click: 'button[class*="card"]' } },
  { path: '/life' },
  { path: '/profile' },
  { path: '/offer' },
  // `/offer/prices` is not here. It is reachable only with a choice in router
  // state and redirects to `/offer` without one, so measuring it would measure
  // the grid a second time under a name that lies about which screen was seen.

  { path: '/my-helper' },
  { path: '/nope' },
];

/**
 * Sub-pixel layout leaves fractions behind; a spacer never weighs four.
 *
 * Everything a screen keeps clear on purpose is already subtracted — it is
 * `.screen`'s own `padding-bottom` in ui.module.css, home indicator included —
 * so this is a tolerance and not an allowance.
 */
const ROUNDING = 4;

const browser = await chromium.launch();
const failures = [];
const skipped = new Set();

/** Stop before measuring anything if the thing being measured is not there. */
async function preflight() {
  const context = await browser.newContext({
    viewport: { width: 390, height: 664 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  const fail = async (why, hint) => {
    console.error(`Cannot measure against ${BASE}: ${why}`);
    console.error(hint);
    await browser.close();
    process.exit(2);
  };

  try {
    const health = await page.goto(`${BASE}/healthz`, { timeout: 15000 });
    if (!health?.ok()) throw new Error(`/healthz answered ${health?.status()}`);
    const body = await page.evaluate(() => document.body.innerText);
    if (!body.includes('"database":"ok"')) {
      throw new Error(`/healthz says ${body.trim().slice(0, 120)}`);
    }
  } catch (error) {
    await fail(
      error.message,
      'Start the dev server (make web) and the API (make api) first.',
    );
  }

  // The home screen's category grid only exists once an authenticated request
  // has come back. Without it every data screen renders an error state, which
  // has a height of its own and would be measured as if it were the screen.
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  const gotData = await page.evaluate(() =>
    Boolean(document.querySelector('[class*="grid"]')),
  );
  if (!gotData) {
    await fail(
      'the home screen came up without its categories',
      'The API is rejecting this init data. Put a signed VITE_MOCK_INIT_DATA in apps/web/.env.local.',
    );
  }
  await context.close();
}

/**
 * How much emptiness the screen has under its lowest visible thing.
 *
 * Runs in the browser. Declared as a plain function so `page.evaluate` can
 * serialise it, inner helper and all.
 */
function look() {
  /**
   * Does this element put anything on the screen *itself*?
   *
   * Its children do not count for it: a container's box is only as meaningful
   * as what is inside it, and a spacer wrapped in a div is still a spacer.
   * What counts is text of its own, a box it fills or outlines, or being one
   * of the elements that draws by nature.
   */
  function paints(el) {
    // Asked first, and of the whole ancestor chain: an element with text in it
    // is still invisible under a hidden or fully transparent parent, and text
    // was the one test that used to answer before anything looked at style.
    if (
      !el.checkVisibility({
        opacityProperty: true,
        visibilityProperty: true,
        contentVisibilityAuto: true,
      })
    ) {
      return false;
    }
    if (/^(svg|img|canvas|video|input|textarea|select|hr)$/i.test(el.tagName))
      return true;
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) return true;
    }
    for (const pseudo of ['::before', '::after']) {
      const drawn = getComputedStyle(el, pseudo);
      if (drawn.content !== 'none' && drawn.content !== 'normal') return true;
    }
    const style = getComputedStyle(el);
    if (style.backgroundImage !== 'none') return true;
    if (!['transparent', 'rgba(0, 0, 0, 0)'].includes(style.backgroundColor)) return true;
    if (style.boxShadow !== 'none') return true;
    if (Number.parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== 'none') {
      return true;
    }
    return ['Top', 'Right', 'Bottom', 'Left'].some(
      (side) => Number.parseFloat(style[`border${side}Width`]) > 0,
    );
  }

  /**
   * Where this element's paint actually stops.
   *
   * `getBoundingClientRect` does not know about clipping, so a tall child of a
   * short `overflow: hidden` box reports a bottom edge nobody can see. Left
   * alone that reads as content below the floor, and one negative number is
   * enough to hide every real spacer above it.
   */
  function visibleBottom(el, screen) {
    let bottom = el.getBoundingClientRect().bottom;
    for (
      let node = el.parentElement;
      node && node !== screen;
      node = node.parentElement
    ) {
      if (getComputedStyle(node).overflowY !== 'visible') {
        bottom = Math.min(bottom, node.getBoundingClientRect().bottom);
      }
    }
    return bottom;
  }

  const doc = document.documentElement;
  const root = document.getElementById('root');
  const screen = root?.firstElementChild;
  if (!screen) return { verdict: 'nothing rendered' };

  const style = getComputedStyle(screen);
  const floor =
    screen.getBoundingClientRect().bottom - Number.parseFloat(style.paddingBottom);

  let lowest = Number.NEGATIVE_INFINITY;
  for (const el of screen.querySelectorAll('*')) {
    // A sheet is fixed to the viewport and is not part of the screen's flow.
    if (getComputedStyle(el).position === 'fixed') continue;
    const box = el.getBoundingClientRect();
    if (box.height <= 0 || box.width <= 0) continue;
    if (!paints(el)) continue;
    lowest = Math.max(lowest, visibleBottom(el, screen));
  }

  // Not "clean": unmeasurable. A page whose root is not a `<Screen>` — which
  // is how the 404 was written — has no content box to measure against, and
  // calling that zero is how a mistyped route reports as spotless. It is the
  // shape of the bug this check twice had to be rescued from, so it is loud.
  if (lowest === Number.NEGATIVE_INFINITY) {
    return { verdict: 'no screen: nothing in the page paints anything' };
  }

  return {
    verdict: 'measured',
    travel: doc.scrollHeight - doc.clientHeight + (root.scrollHeight - root.clientHeight),
    // Everything between the last visible thing and where the screen's own
    // designed clearance begins.
    dead: floor - lowest,
  };
}

async function measure(page, name, label) {
  await page.waitForTimeout(900);
  // The development console is a floating panel of its own and would otherwise
  // count as content.
  await page.addStyleTag({ content: '#eruda{display:none !important}' });
  await page.waitForTimeout(100);

  const seen = await page.evaluate(look);
  if (seen.verdict !== 'measured') {
    console.error(`\n${name} at ${label}: ${seen.verdict}.`);
    await browser.close();
    process.exit(2);
  }

  // Dead space nobody can reach is just whitespace at the foot of a page.
  const dead = seen.travel > 0 ? Math.round(seen.dead) : 0;
  const pointless = dead > ROUNDING;
  console.log(
    `  ${pointless ? 'FAIL' : 'ok  '} ${name.padEnd(20)}` +
      ` travel=${Math.round(seen.travel)}px  empty=${dead}px`,
  );
  if (pointless) failures.push(`${name} at ${label}: ${dead}px of nothing`);
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
      const response = await page.goto(`${BASE}${route.path}`, {
        waitUntil: 'networkidle',
      });
      if (response && !response.ok()) throw new Error(`HTTP ${response.status()}`);
    } catch (error) {
      console.error(`\nCannot reach ${BASE}${route.path}: ${error.message}`);
      await browser.close();
      process.exit(2);
    }

    await measure(page, route.path, label);

    if (route.into) {
      let opened = true;
      try {
        await page.locator(route.into.click).first().click({ timeout: 5000 });
        await page.waitForURL((url) => url.pathname !== route.path, { timeout: 5000 });
      } catch {
        opened = false;
      }
      if (opened) {
        await measure(page, route.into.name, label);
      } else {
        // An empty list is a seeding problem rather than a layout one, so it
        // does not fail the run — but it does mean a screen went unmeasured,
        // and an unmeasured screen reported as nothing at all is how a check
        // like this quietly stops being one.
        console.log(
          `  SKIP ${route.into.name.padEnd(20)} nothing in ${route.path} to open`,
        );
        skipped.add(route.into.name);
      }
    }

    await page.close();
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
if (skipped.size) {
  console.log(`\nNot measured, nothing to open: ${[...skipped].join(', ')}.`);
}
console.log(`Every screen measured ends on content, at all ${VIEWPORTS.length} sizes.`);
