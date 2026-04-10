import { useState, useCallback } from 'react';
import type { ReactNode } from 'react';
import { CreateRunContext } from './createRunContextValue';

export function CreateRunProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [preSelectedRoutine, setPreSelectedRoutine] = useState<string | null>(null);

  const open = useCallback((routineId?: string) => {
    setPreSelectedRoutine(routineId ?? null);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    // Clear pre-selection when modal closes
    setPreSelectedRoutine(null);
  }, []);

  return (
    <CreateRunContext.Provider value={{ isOpen, open, close, preSelectedRoutine }}>
      {children}
    </CreateRunContext.Provider>
  );
}
