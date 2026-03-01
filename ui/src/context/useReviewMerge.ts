import { useContext } from 'react';
import { ReviewMergeContext } from './ReviewMergeContextValue';

export function useReviewMerge() {
  const context = useContext(ReviewMergeContext);
  if (!context) {
    throw new Error('useReviewMerge must be used within ReviewMergeProvider');
  }
  return context;
}
