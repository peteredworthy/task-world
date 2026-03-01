import { useState, type ReactNode } from 'react';
import { ReviewMergeContext } from './ReviewMergeContextValue';

export function ReviewMergeProvider({ children }: { children: ReactNode }) {
  const [isPruneMode, setIsPruneMode] = useState(false);
  const [showBackMergeModal, setShowBackMergeModal] = useState(false);

  return (
    <ReviewMergeContext.Provider
      value={{
        isPruneMode,
        onTogglePruneMode: () => setIsPruneMode(v => !v),
        showBackMergeModal,
        onOpenBackMergeModal: () => setShowBackMergeModal(true),
        onCloseBackMergeModal: () => setShowBackMergeModal(false),
      }}
    >
      {children}
    </ReviewMergeContext.Provider>
  );
}
