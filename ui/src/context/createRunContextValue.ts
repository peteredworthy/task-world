import { createContext } from 'react';

export interface CreateRunContextValue {
  isOpen: boolean;
  open: (routineId?: string) => void;
  close: () => void;
  preSelectedRoutine: string | null;
}

export const CreateRunContext = createContext<CreateRunContextValue | null>(null);
