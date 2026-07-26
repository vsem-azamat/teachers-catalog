import { fileURLToPath, URL } from 'node:url';
import { lingui, linguiTransformerBabelPreset } from '@lingui/vite-plugin';
import babel from '@rolldown/plugin-babel';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import mkcert from 'vite-plugin-mkcert';

/**
 * The API this app talks to. Proxied in development so the browser sees a
 * same-origin request: since 20 July 2026 Telegram only allows Mini App API
 * calls from the app's own origin, and matching that locally keeps the dev
 * environment honest.
 */
// 8010, not 8000: something else on the development machine holds 8000,
// and a proxy pointing at the wrong server fails as a blank screen.
const API_TARGET = 'http://127.0.0.1:8010';

/**
 * Escape hatch for environments where mkcert cannot install its CA.
 *
 * The first run of mkcert needs `sudo` to write into the system trust store,
 * which is impossible in CI and awkward on a locked-down machine. Set
 * `VITE_NO_HTTPS=1` to serve over plain HTTP: enough to work on components in a
 * desktop browser, but Telegram will refuse to load the app, so it is not a way
 * to test inside the client.
 */
const httpsDisabled = process.env.VITE_NO_HTTPS === '1';

export default defineConfig({
  plugins: [
    react(),
    // Compiles src/locales/*/messages.po into loadable JS modules.
    lingui(),
    // @vitejs/plugin-react v6 transforms with oxc and no longer runs Babel, so
    // the Lingui macros need their own Babel pass to be expanded.
    babel({ presets: [linguiTransformerBabelPreset()] }),
    // Telegram refuses to load a Mini App over plain HTTP.
    ...(httpsDisabled ? [] : [mkcert()]),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Listen on every interface so a phone on the same network can reach it.
    host: true,
    port: 5173,
    // Vite refuses requests whose Host it does not know, which is what stops
    // a hostile page in the browser from talking to the dev server through
    // DNS rebinding. A quick tunnel arrives under a hostname Vite has never
    // seen, so the tunnel's domain is allowed — the domain, not everything.
    allowedHosts: [
      '.trycloudflare.com',
      ...(process.env.VITE_ALLOWED_HOST ? [process.env.VITE_ALLOWED_HOST] : []),
    ],
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/healthz': { target: API_TARGET, changeOrigin: true },
      // The bot webhook goes through the same origin as the app, so one
      // tunnel serves both — which is also how it is deployed.
      '/tg': { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: {
    host: true,
    port: 5173,
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
});
