import { createContext } from 'react';

export interface ReviewMergeContextValue {
  isPruneMode: boolean;
  onTogglePruneMode: () => void;
  showBackMergeModal: boolean;
  onOpenBackMergeModal: () => void;
  onCloseBackMergeModal: () => void;
}

export const ReviewMergeContext = createContext<ReviewMergeContextValue | undefined>(undefined);
