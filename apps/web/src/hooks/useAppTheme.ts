import { useCallback, useEffect, useState } from 'react';

import { paintChrome } from '@/hooks/useTelegram';
import {
  applyTheme,
  readThemeChoice,
  type Theme,
  type ThemeChoice,
  watchSystemTheme,
  writeThemeChoice,
} from '@/lib/theme';

export interface AppTheme {
  /** What the person chose: system, light or dark. */
  choice: ThemeChoice;
  /** What that resolves to right now. */
  theme: Theme;
  set: (choice: ThemeChoice) => void;
}

/**
 * The palette, and the control over it.
 *
 * Reads the stored choice rather than the attribute the inline boot script
 * wrote: the attribute only ever says light or dark, and "system" has to
 * survive a reload as itself, or a phone that flips at sunset would be stuck
 * on whatever it happened to be when the page loaded.
 */
export function useAppTheme(): AppTheme {
  const [choice, setChoice] = useState<ThemeChoice>(readThemeChoice);
  const [theme, setTheme] = useState<Theme>(() => applyTheme(readThemeChoice()));

  const set = useCallback((next: ThemeChoice) => {
    setChoice(next);
    writeThemeChoice(next);
    setTheme(applyTheme(next));
    // Telegram paints the frame around the page, and it does not read our
    // stylesheet. Without this the header stays the old colour.
    paintChrome();
  }, []);

  useEffect(() => {
    if (choice !== 'system') return;
    return watchSystemTheme(() => {
      setTheme(applyTheme('system'));
      paintChrome();
    });
  }, [choice]);

  return { choice, theme, set };
}
