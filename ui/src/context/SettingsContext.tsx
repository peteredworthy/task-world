import { useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { SettingsContext } from './settingsContextValue';

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => {
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  return (
    <SettingsContext.Provider value={{ isOpen, open, close }}>
      {children}
    </SettingsContext.Provider>
  );
}
