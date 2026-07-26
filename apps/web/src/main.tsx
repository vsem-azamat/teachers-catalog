import { I18nProvider } from '@lingui/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  backButton,
  init,
  initData,
  isTMA,
  mainButton,
  miniApp,
  themeParams,
  viewport,
} from '@tma.js/sdk-react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';

import { paintChrome } from '@/hooks/useTelegram';
import { activateLocale, i18n, normalizeLocale, resolveLocale } from '@/i18n';
import { ApiError } from '@/lib/api';
import LandingPage from '@/pages/Landing';
import { router } from '@/router';

import './index.css';

/**
 * Startup, in order: fake the Telegram environment if we are not in it, bring
 * up the SDK, pick a language, then render. Each step depends on the one before
 * it, which is why this is a sequence and not a set of effects.
 */
async function bootstrap(): Promise<void> {
  // Before anything else, and in particular before the mock: outside Telegram
  // there is no account, no chat to notify and nothing to sign a request
  // with, so the catalog cannot run. That is a landing page, not an error.
  if (showLanding()) {
    await renderLanding();
    return;
  }

  if (import.meta.env.DEV) {
    // Dynamic import so the mock never reaches the production bundle.
    const { mockEnv } = await import('@/mockEnv');
    mockEnv();
    await enableMobileConsole();
  }

  initSdk();
  await initLocale();
  render();
}

/**
 * Is this a browser rather than Telegram?
 *
 * `?landing` forces it either way, which is the only way to see the page in
 * development: the mock has not run yet at this point, so `isTMA()` would say
 * no to every local session and the app would never start.
 */
function showLanding(): boolean {
  if (new URLSearchParams(window.location.search).has('landing')) return true;
  if (import.meta.env.DEV) return false;
  return !isTMA();
}

async function renderLanding(): Promise<void> {
  const locale = normalizeLocale(navigator.language);
  await activateLocale(locale);
  document.documentElement.lang = locale;

  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <LandingPage />
      </I18nProvider>
    </StrictMode>,
  );
}

/**
 * Bring up the SDK and mount the features this app uses.
 *
 * Mounting is per-feature and not free, so only what is actually used is
 * mounted. `bindCssVars` publishes Telegram's palette and its insets as CSS
 * variables; the app uses the insets for layout but keeps its own colours, and
 * hands those colours back to Telegram so the chrome around the page matches.
 */
function initSdk(): void {
  init();

  themeParams.mount.ifAvailable();
  themeParams.bindCssVars.ifAvailable();

  // Async: the viewport has to ask the client for its dimensions. Nothing
  // downstream waits on it, so the promise is deliberately not awaited — the
  // signals simply start out at zero and fill in.
  const mounted = viewport.mount.ifAvailable();
  if (mounted.ok) {
    void Promise.resolve(mounted.data)
      .then(() => {
        viewport.bindCssVars.ifAvailable();
      })
      .catch((error: unknown) => {
        console.error('[tma] viewport failed to mount', error);
      });
  }

  // Mounted here, driven from components via the hooks in @/hooks/useTelegram.
  backButton.mount.ifAvailable();
  mainButton.mount.ifAvailable();

  miniApp.mount.ifAvailable();
  // The palette is already on the document — index.html resolves it before the
  // first paint — so Telegram can be told the right colour straight away.
  paintChrome();

  initData.restore();
}

/** Load the one catalog we need before the first paint, to avoid a flash. */
async function initLocale(): Promise<void> {
  const locale = resolveLocale(initData.user()?.language_code);
  await activateLocale(locale);
  document.documentElement.lang = locale;
}

/**
 * A console on the phone itself.
 *
 * Remote debugging a Mini App on iOS means a cable and a Mac; this is the
 * cheaper 90% of it. Development only.
 */
async function enableMobileConsole(): Promise<void> {
  try {
    const { default: eruda } = await import('eruda');
    eruda.init();
  } catch (error) {
    console.warn('[dev] eruda failed to load', error);
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Mobile data. Refetching on every window focus is a poor trade here.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // Nothing the client got wrong gets better by asking again: rejected
        // init data stays rejected, and a profile that does not exist will
        // not appear. Retrying only delays the message the user needs, which
        // is why a missing profile used to sit on a skeleton for seconds.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false;
        }
        return failureCount < 2;
      },
    },
  },
});

function render(): void {
  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>
    </StrictMode>,
  );
}

bootstrap().catch((error: unknown) => {
  // Reaching here means the app never rendered, so there is no error boundary
  // to catch it and no UI to report it in. Say something in plain text rather
  // than leaving a white screen.
  console.error('[boot] failed to start', error);

  const container = document.getElementById('root');
  if (container) {
    const message =
      error instanceof Error && /launch params|unknown env/i.test(error.message)
        ? 'This app has to be opened from Telegram.'
        : 'Something went wrong while starting up. Please reopen the app.';
    container.textContent = message;
  }
});
