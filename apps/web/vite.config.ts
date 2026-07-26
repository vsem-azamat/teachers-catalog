import { fileURLToPath, URL } from 'node:url';

import babel from '@rolldown/plugin-babel';
import { lingui, linguiTransformerBabelPreset } from '@lingui/vite-plugin';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import mkcert from 'vite-plugin-mkcert';

/**
 * The API this app talks to. Proxied in development so the browser sees a
 * same-origin request: since 20 July 2026 Telegram only allows Mini App API
 * calls from the app's own origin, and matching that locally keeps the dev
 * environment honest.
 */
const API_TARGET = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [
    react(),
    // Compiles src/locales/*/messages.po into loadable JS modules.
    lingui(),
    // @vitejs/plugin-react v6 transforms with oxc and no longer runs Babel, so
    // the Lingui macros need their own Babel pass to be expanded.
    babel({ presets: [linguiTransformerBabelPreset()] }),
    // Telegram refuses to load a Mini App over plain HTTP.
    mkcert(),
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
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/healthz': { target: API_TARGET, changeOrigin: true },
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
