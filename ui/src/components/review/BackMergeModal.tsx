import { useEffect, useRef } from 'react';
import { useBackMerge } from '../../hooks/useReview';
import { Spinner } from '../Spinner';
import { ApiError } from '../../api/client';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import type { BranchStatusResponse } from '../../types';
import type { BackMergeResponse } from '../../types/review';

interface BackMergeModalProps {
  isOpen: boolean;
  onClose: () => void;
  runId: string;
  branchStatus: BranchStatusResponse | null;
  onMergeComplete: (result: BackMergeResponse) => void;
}

export function BackMergeModal({
  isOpen,
  onClose,
  runId,
  branchStatus,
  onMergeComplete,
}: BackMergeModalProps) {
  const backMerge = useBackMerge(runId);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Reset on open
  useEffect(() => {
    if (isOpen) {
      backMerge.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Escape to close (unless running)
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !backMerge.isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, backMerge.isPending]);

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

  const sourceBranch = branchStatus?.source_branch ?? '(target branch)';
  const runBranch = branchStatus?.run_branch ?? '(run branch)';
  const predictedConflicts = branchStatus?.predicted_conflict_count ?? 0;
  const behindCount = branchStatus?.behind_count ?? 0;

  async function handleConfirm() {
    try {
      const result = await backMerge.mutateAsync();
      onMergeComplete(result);
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  const mergeError =
    backMerge.error instanceof ApiError
      ? backMerge.error.message
      : backMerge.error
        ? 'Back merge failed. Please try again.'
        : null;

  const titleId = 'back-merge-modal-title';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={() => {
        if (!backMerge.isPending) onClose();
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
              Back Merge
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Merge the target branch into the run branch.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              if (!backMerge.isPending) onClose();
            }}
            disabled={backMerge.isPending}
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
          {/* Branch info */}
          <div className="rounded-lg border border-border bg-bg-card px-4 py-3 space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wide text-text-muted w-20 shrink-0">Source</span>
              <code className="text-xs font-mono text-accent-blue bg-accent-blue/10 px-2 py-0.5 rounded truncate">
                {sourceBranch}
              </code>
            </div>
            <div className="flex items-start gap-2 pl-1">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-text-muted mt-0.5 shrink-0"
              >
                <line x1="12" y1="5" x2="12" y2="19" />
                <polyline points="19 12 12 19 5 12" />
              </svg>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wide text-text-muted w-20 shrink-0">Target</span>
              <code className="text-xs font-mono text-accent-purple bg-accent-purple/10 px-2 py-0.5 rounded truncate">
                {runBranch}
              </code>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-md border border-border bg-bg-muted px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-text-muted">Commits behind</p>
              <p className="mt-0.5 text-xl font-semibold text-text-primary">{behindCount}</p>
            </div>
            <div
              className={`rounded-md border px-3 py-2 ${
                predictedConflicts > 0
                  ? 'border-status-failed/30 bg-status-failed/8'
                  : 'border-border bg-bg-muted'
              }`}
            >
              <p className="text-[10px] uppercase tracking-wide text-text-muted">Predicted conflicts</p>
              <p
                className={`mt-0.5 text-xl font-semibold ${
                  predictedConflicts > 0 ? 'text-status-failed' : 'text-text-primary'
                }`}
              >
                {predictedConflicts}
              </p>
            </div>
          </div>

          {predictedConflicts > 0 && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/8 px-3 py-2">
              <p className="text-xs text-amber-400">
                This merge may produce conflicts that will need to be resolved.
              </p>
            </div>
          )}

          {/* Progress indicator */}
          {backMerge.isPending && (
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
            disabled={backMerge.isPending}
            className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={backMerge.isPending}
            className="px-5 py-2 text-sm font-medium text-white bg-accent-blue rounded-md hover:bg-accent-blue/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {backMerge.isPending ? (
              <>
                <Spinner className="h-4 w-4" />
                <span>Merging…</span>
              </>
            ) : (
              <span>Confirm Merge</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
