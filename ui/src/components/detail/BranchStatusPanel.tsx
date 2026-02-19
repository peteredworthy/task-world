import { useState } from 'react';
import { ApiError } from '../../api/client';
import { useBackMerge, useBranchStatus } from '../../hooks/useApi';

interface BranchStatusPanelProps {
  runId: string;
}

export function BranchStatusPanel({ runId }: BranchStatusPanelProps) {
  const { data, isLoading, isError, error, refetch } = useBranchStatus(runId);
  const backMerge = useBackMerge(runId);
  const [actionError, setActionError] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="mb-6 rounded-md border border-border bg-bg-elevated p-4">
        <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Branch Status</h2>
        <p className="mt-2 text-sm text-text-muted">Loading branch status...</p>
      </div>
    );
  }

  if (isError || !data) {
    const message = error instanceof ApiError ? error.message : 'Failed to load branch status.';

    return (
      <div className="mb-6 rounded-md border border-status-failed/30 bg-status-failed/10 p-4">
        <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Branch Status</h2>
        <p className="mt-2 text-sm text-status-failed">{message}</p>
        <button
          onClick={() => void refetch()}
          className="mt-3 rounded-md border border-status-failed/40 px-3 py-1.5 text-xs font-medium text-status-failed hover:bg-status-failed/10"
        >
          Retry
        </button>
      </div>
    );
  }

  const hasConflicts = data.has_conflicts || !data.can_merge_cleanly;

  return (
    <div className="mb-6 rounded-md border border-border bg-bg-elevated p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">Branch Status</h2>
          <p className="mt-1 text-xs text-text-muted">
            <span className="font-mono text-text-secondary">{data.source_branch}</span>
            {' -> '}
            <span className="font-mono text-text-secondary">{data.run_branch}</span>
          </p>
        </div>
        <button
          onClick={() => {
            setActionError(null);
            backMerge.mutate(undefined, {
              onError: (mutationError: Error) => {
                setActionError(
                  mutationError instanceof ApiError
                    ? mutationError.message
                    : 'Failed to pull upstream changes.',
                );
              },
            });
          }}
          disabled={hasConflicts || backMerge.isPending}
          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {backMerge.isPending ? 'Pulling...' : 'Pull upstream changes'}
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:max-w-xs">
        <div className="rounded-md border border-border bg-bg-muted px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">Behind</p>
          <p className="mt-1 text-lg font-semibold text-text-primary">{data.behind_count}</p>
        </div>
        <div className="rounded-md border border-border bg-bg-muted px-3 py-2">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">Ahead</p>
          <p className="mt-1 text-lg font-semibold text-text-primary">{data.ahead_count}</p>
        </div>
      </div>

      {hasConflicts && (
        <div className="mt-3 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2">
          <p className="text-xs font-medium text-yellow-800">
            Merge conflicts detected. Resolve conflicts before pulling upstream changes.
          </p>
        </div>
      )}

      {actionError && (
        <p className="mt-3 text-xs text-status-failed">{actionError}</p>
      )}
    </div>
  );
}
