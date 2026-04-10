import { useContext } from 'react';
import { CreateRunContext } from '../context/createRunContextValue';
import type { CreateRunContextValue } from '../context/createRunContextValue';

export function useCreateRunModal(): CreateRunContextValue {
  const ctx = useContext(CreateRunContext);
  if (!ctx) {
    throw new Error('useCreateRunModal must be used within a CreateRunProvider');
  }
  return ctx;
}
