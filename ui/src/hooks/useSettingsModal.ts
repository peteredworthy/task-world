import { useContext } from 'react';
import { SettingsContext } from '../context/settingsContextValue';
import type { SettingsContextValue } from '../context/settingsContextValue';

export function useSettingsModal(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  /* v8 ignore next 3 -- outside-provider misuse guard; unreachable in correct usage */
  if (!ctx) {
    throw new Error('useSettingsModal must be used within a SettingsProvider');
  }
  return ctx;
}
