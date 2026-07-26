import { defineConfig } from '@lingui/cli';

/**
 * Four interface languages, matching the `UiLang` enum on the API side.
 *
 * Only chrome lives here. Names of subjects, faculties and service types are
 * translated in the database and arrive from the API already localised, so they
 * must never end up in these catalogs.
 */
export default defineConfig({
  sourceLocale: 'ru',
  locales: ['ru', 'cs', 'en', 'uk'],
  catalogs: [
    {
      path: '<rootDir>/src/locales/{locale}/messages',
      include: ['<rootDir>/src'],
      exclude: ['**/node_modules/**', '**/locales/**'],
    },
  ],
  format: 'po',
  compileNamespace: 'ts',
  orderBy: 'messageId',
});
