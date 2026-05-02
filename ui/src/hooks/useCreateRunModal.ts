import { useContext } from 'react';
import { CreateRunContext } from '../context/createRunContextValue';
import type { CreateRunContextValue } from '../context/createRunContextValue';

export function useCreateRunModal(): CreateRunContextValue {
  const ctx = useContext(CreateRunContext);
  /* v8 ignore next 3 -- outside-provider misuse guard; unreachable in correct usage */
  if (!ctx) {
    throw new Error('useCreateRunModal must be used within a CreateRunProvider');
  }
  return ctx;
}
