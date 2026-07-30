import { defineConfig } from '@hey-api/openapi-ts';

/**
 * Generates a typed client from the API's OpenAPI document.
 *
 * Run it through `make contract` from the repository root, which dumps the
 * document to a file first and then checks the result against what is
 * committed. Pointing this at a running API instead works, and writes that
 * server's address into the client as a literal `ClientOptions.baseUrl` — a
 * client that carries whichever machine generated it, and that the contract
 * check rejects. A file has no URL to bake in.
 *
 * Not wired into `pnpm build` on purpose: a build that fails because a backend
 * is not running is a bad build. Everything the generator has not covered yet
 * is hand-written in `src/lib/types.ts`.
 */
export default defineConfig({
  input: process.env.OPENAPI_URL ?? 'http://127.0.0.1:8000/openapi.json',
  // Biome is excluded from the generated directory, so leave formatting and
  // linting to it rather than having the generator shell out to a second tool.
  output: './src/lib/generated',
  plugins: ['@hey-api/typescript'],
});
