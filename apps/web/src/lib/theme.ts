/**
 * Which palette the page wears, and who decides.
 *
 * Three choices, not two. "System" is the honest default — most people never
 * touch this — but it cannot be the only option: a Mini App is opened from
 * inside a client that has a theme of its own, and someone reading in a dark
 * Telegram at midday is entitled to a light catalog. The resolved answer is
 * written to `data-theme` on the root element, which is the only thing
 * `styles/tokens.css` looks at.
 *
 * The same key and the same resolution are duplicated, deliberately, by the
 * inline script in index.html — that copy runs before the first paint, so the
 * page never flashes the wrong palette. Keep the two in step.
 */

export const THEME_CHOICES = ['system', 'light', 'dark'] as const;

export type ThemeChoice = (typeof THEME_CHOICES)[number];

/** What `data-theme` ends up saying: "system" is not a palette. */
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'konnekt.theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return (
    typeof value === 'string' && (THEME_CHOICES as readonly string[]).includes(value)
  );
}

export function readThemeChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isThemeChoice(stored) ? stored : 'system';
  } catch {
    // Private mode, or storage disabled. Following the system is a fine
    // answer for someone whose choice we cannot remember anyway.
    return 'system';
  }
}

export function writeThemeChoice(choice: ThemeChoice): void {
  try {
    if (choice === 'system') localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // Ignore — the choice simply will not survive a restart.
  }
}

export function systemTheme(): Theme {
  return typeof matchMedia === 'function' && matchMedia(DARK_QUERY).matches
    ? 'dark'
    : 'light';
}

export function resolveTheme(choice: ThemeChoice): Theme {
  return choice === 'system' ? systemTheme() : choice;
}

/** Put the resolved palette on the document, and say which one it was. */
export function applyTheme(choice: ThemeChoice): Theme {
  const theme = resolveTheme(choice);
  document.documentElement.dataset.theme = theme;
  return theme;
}

/**
 * Follow the operating system while the choice is "system".
 *
 * Returns the unsubscribe function. Worth wiring up: a phone that switches to
 * dark at sunset does it while the app is open.
 */
export function watchSystemTheme(onChange: (theme: Theme) => void): () => void {
  if (typeof matchMedia !== 'function') return () => {};
  const query = matchMedia(DARK_QUERY);
  const listener = (event: MediaQueryListEvent) => {
    onChange(event.matches ? 'dark' : 'light');
  };
  query.addEventListener('change', listener);
  return () => query.removeEventListener('change', listener);
}
