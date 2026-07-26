import { defineConfig } from '@hey-api/openapi-ts';

/**
 * Generates a typed client from the running API.
 *
 * Not wired into `pnpm build` on purpose: the generator needs the API process
 * up, and a build that fails because a backend is not running is a bad build.
 * Run `pnpm api:generate` by hand after changing the API, and commit the
 * result. Until that happens, `src/lib/types.ts` is written by hand.
 */
export default defineConfig({
  input: process.env.OPENAPI_URL ?? 'http://127.0.0.1:8000/openapi.json',
  // Biome is excluded from the generated directory, so leave formatting and
  // linting to it rather than having the generator shell out to a second tool.
  output: './src/lib/generated',
  plugins: ['@hey-api/typescript'],
});
