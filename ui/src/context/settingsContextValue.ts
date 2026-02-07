import { createContext } from 'react';

export interface SettingsContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
}

export const SettingsContext = createContext<SettingsContextValue | null>(null);
