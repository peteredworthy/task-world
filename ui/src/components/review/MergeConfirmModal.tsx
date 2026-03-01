import { useEffect, useRef, useState } from 'react';
import { useFinalMergeBack } from '../../hooks/useReview';
import { Spinner } from '../Spinner';
import { ApiError } from '../../api/client';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import type { FinalMergeBackResponse } from '../../types/review';

interface MergeConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  runId: string;
  onMergeComplete: (result: FinalMergeBackResponse) => void;
}

export function MergeConfirmModal({
  isOpen,
  onClose,
  runId,
  onMergeComplete,
}: MergeConfirmModalProps) {
  const [strategy, setStrategy] = useState<'squash' | 'merge'>('squash');
  const mergeBack = useFinalMergeBack(runId);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Reset state on open
  useEffect(() => {
    if (isOpen) {
      setStrategy('squash');
      mergeBack.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Escape to close (unless running)
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !mergeBack.isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, mergeBack.isPending]);

  // Scroll lock
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  useFocusTrap(dialogRef, isOpen);

  if (!isOpen) return null;

  async function handleConfirm() {
    try {
      const result = await mergeBack.mutateAsync(strategy);
      onMergeComplete(result);
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  const mergeError =
    mergeBack.error instanceof ApiError
      ? mergeBack.error.message
      : mergeBack.error
        ? 'Merge failed. Please try again.'
        : null;

  const titleId = 'merge-confirm-modal-title';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={() => {
        if (!mergeBack.isPending) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[480px] mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border shrink-0">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-text-primary">
              Commit Merge Back
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Merge the run branch into the target branch.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              if (!mergeBack.isPending) onClose();
            }}
            disabled={mergeBack.isPending}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover disabled:opacity-40"
            aria-label="Close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4 min-h-0">
          {/* Strategy selection */}
          <fieldset>
            <legend className="text-sm font-medium text-text-primary mb-3">Merge strategy</legend>
            <div className="space-y-2">
              {/* Squash option */}
              <label
                className={`flex items-start gap-3 rounded-lg border px-4 py-3 cursor-pointer transition-colors ${
                  strategy === 'squash'
                    ? 'border-accent-blue/60 bg-accent-blue/8'
                    : 'border-border hover:border-border-hover hover:bg-bg-hover'
                }`}
              >
                <input
                  type="radio"
                  name="merge-strategy"
                  value="squash"
                  checked={strategy === 'squash'}
                  onChange={() => setStrategy('squash')}
                  disabled={mergeBack.isPending}
                  className="mt-0.5 accent-accent-blue"
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">
                    Squash merge
                    <span className="ml-2 text-[10px] uppercase tracking-wide font-semibold text-accent-blue bg-accent-blue/10 px-1.5 py-0.5 rounded">
                      recommended
                    </span>
                  </p>
                  <p className="text-xs text-text-muted mt-0.5">
                    Combines all run commits into a single commit on the target branch. Keeps history clean.
                  </p>
                </div>
              </label>

              {/* Merge commit option */}
              <label
                className={`flex items-start gap-3 rounded-lg border px-4 py-3 cursor-pointer transition-colors ${
                  strategy === 'merge'
                    ? 'border-accent-blue/60 bg-accent-blue/8'
                    : 'border-border hover:border-border-hover hover:bg-bg-hover'
                }`}
              >
                <input
                  type="radio"
                  name="merge-strategy"
                  value="merge"
                  checked={strategy === 'merge'}
                  onChange={() => setStrategy('merge')}
                  disabled={mergeBack.isPending}
                  className="mt-0.5 accent-accent-blue"
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">Merge commit</p>
                  <p className="text-xs text-text-muted mt-0.5">
                    Creates a merge commit that preserves the full run branch history.
                  </p>
                </div>
              </label>
            </div>
          </fieldset>

          {/* Progress indicator */}
          {mergeBack.isPending && (
            <div className="flex items-center gap-3 rounded-lg border border-accent-blue/30 bg-accent-blue/8 px-4 py-3">
              <Spinner className="h-4 w-4 shrink-0" />
              <p className="text-sm text-text-secondary">Merging branches…</p>
            </div>
          )}

          {/* Error */}
          {mergeError && (
            <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
              <p className="text-sm text-status-failed">{mergeError}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-6 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={mergeBack.isPending}
            className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={mergeBack.isPending}
            className="px-5 py-2 text-sm font-medium text-white bg-accent-blue rounded-md hover:bg-accent-blue/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {mergeBack.isPending ? (
              <>
                <Spinner className="h-4 w-4" />
                <span>Merging…</span>
              </>
            ) : (
              <span>Merge</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
