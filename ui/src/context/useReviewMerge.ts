import { useContext } from 'react';
import { ReviewMergeContext } from './ReviewMergeContextValue';

export function useReviewMerge() {
  const context = useContext(ReviewMergeContext);
  /* v8 ignore next 3 -- outside-provider misuse guard; unreachable in correct usage */
  if (!context) {
    throw new Error('useReviewMerge must be used within ReviewMergeProvider');
  }
  return context;
}
