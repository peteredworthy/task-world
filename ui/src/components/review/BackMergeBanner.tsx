import { useState } from 'react';
import { useRevertBackMerge } from '../../hooks/useReview';
import { Spinner } from '../Spinner';
import { ApiError } from '../../api/client';

interface BackMergeBannerProps {
  runId: string;
  /** SHA of the merge commit. When null, branch was already up-to-date (clean noop). */
  mergeCommitSha: string | null;
  onDismiss: () => void;
  onReverted?: () => void;
}

export function BackMergeBanner({
  runId,
  mergeCommitSha,
  onDismiss,
  onReverted,
}: BackMergeBannerProps) {
  const revert = useRevertBackMerge(runId);
  const [revertError, setRevertError] = useState<string | null>(null);

  const shortSha = mergeCommitSha ? mergeCommitSha.slice(0, 7) : null;

  async function handleUndo() {
    setRevertError(null);
    try {
      await revert.mutateAsync();
      onReverted?.();
      onDismiss();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : 'Failed to revert back merge. Please try again.';
      setRevertError(message);
    }
  }

  return (
    <div className="rounded-lg border border-status-active/30 bg-status-active/8 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          {/* Success icon */}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-status-active mt-0.5 shrink-0"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <div className="min-w-0">
            {shortSha ? (
              <>
                <p className="text-sm font-medium text-text-primary">Back merge complete</p>
                <p className="text-xs text-text-muted mt-0.5">
                  Merge commit{' '}
                  <code className="font-mono text-text-secondary">{shortSha}</code>
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-text-primary">Back merge clean</p>
                <p className="text-xs text-text-muted mt-0.5">
                  Branch is already up-to-date with the target
                </p>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Undo button — only shown when there's a merge commit to revert */}
          {shortSha && (
            <button
              type="button"
              onClick={() => void handleUndo()}
              disabled={revert.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-secondary border border-border rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Revert this back merge commit"
            >
              {revert.isPending ? (
                <>
                  <Spinner className="h-3 w-3" />
                  <span>Undoing…</span>
                </>
              ) : (
                <>
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
                  >
                    <path d="M3 7v6h6" />
                    <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
                  </svg>
                  <span>Undo</span>
                </>
              )}
            </button>
          )}

          {/* Dismiss button */}
          <button
            type="button"
            onClick={onDismiss}
            disabled={revert.isPending}
            className="text-text-muted hover:text-text-primary transition-colors p-1 rounded-md hover:bg-bg-hover disabled:opacity-40"
            aria-label="Dismiss"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
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
      </div>

      {/* Error state */}
      {revertError && (
        <div className="mt-2 rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
          <p className="text-xs text-status-failed">{revertError}</p>
        </div>
      )}
    </div>
  );
}
