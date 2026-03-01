import { useState } from 'react';
import type { ViewType } from 'react-diff-view';
import { ApiError } from '../../api/client';
import { useDiff } from '../../hooks/useReview';
import { DiffViewer } from './DiffViewer';

interface DiffPanelProps {
  runId: string;
  filePath: string | null;
  diffScope?: 'aggregate' | 'task';
  diffRef?: string;
  selectionSummary?: string;
}

export function DiffPanel({
  runId,
  filePath,
  diffScope = 'aggregate',
  diffRef,
  selectionSummary = 'All work',
}: DiffPanelProps) {
  const [viewType, setViewType] = useState<ViewType>('split');

  const diffEnabled = filePath ? diffScope === 'aggregate' || diffRef !== undefined : true;

  const { data, isLoading, isError, error, refetch } = useDiff(
    diffEnabled && filePath ? runId : undefined,
    diffScope,
    diffRef,
  );

  const errorMessage = error instanceof ApiError ? error.message : 'Failed to load diff.';

  return (
    <div className="flex h-full min-h-0 flex-col rounded-md border border-border-hover bg-bg-elevated">
      <div className="flex items-center gap-2 border-b border-border-hover px-4 py-3">
        <div className="min-w-0 flex-1">
          {filePath ? (
            <>
              <p className="truncate font-mono text-xs text-text-primary" title={filePath}>
                {filePath}
              </p>
              <p className="mt-0.5 text-[11px] text-text-muted">
                Review selected file diff · {selectionSummary}
              </p>
            </>
          ) : (
            <>
              <p className="text-xs font-semibold uppercase tracking-wide text-text-primary">
                Diff Viewer
              </p>
              <p className="mt-0.5 text-[11px] text-text-muted">Select a file to view its diff.</p>
            </>
          )}
        </div>

        <div className="relative grid grid-cols-2 w-32 rounded-md border border-border-hover bg-bg-card p-0.5 shrink-0">
          <span
            className={
              'pointer-events-none absolute top-0.5 bottom-0.5 left-0.5 w-[calc(50%-2px)] rounded bg-bg-hover transition-transform duration-200 ease-out ' +
              (viewType === 'split' ? 'translate-x-full' : 'translate-x-0')
            }
          />
          <button
            type="button"
            disabled={!filePath}
            onClick={() => setViewType('unified')}
            className={
              'relative z-10 px-2 py-0.5 text-xs rounded transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
              (viewType === 'unified'
                ? 'text-text-primary font-semibold'
                : 'text-text-muted hover:text-text-secondary')
            }
          >
            Inline
          </button>
          <button
            type="button"
            disabled={!filePath}
            onClick={() => setViewType('split')}
            className={
              'relative z-10 px-2 py-0.5 text-xs rounded transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
              (viewType === 'split'
                ? 'text-text-primary font-semibold'
                : 'text-text-muted hover:text-text-secondary')
            }
          >
            Split
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {!filePath ? (
          <div className="flex h-full items-center justify-center rounded border border-dashed border-border bg-bg-primary/30">
            <p className="text-sm text-text-muted">Select a file from the left panel.</p>
          </div>
        ) : diffScope === 'task' && !diffRef ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">No commit range available for the current task selection.</p>
          </div>
        ) : isLoading ? (
          <div className="flex flex-col gap-3" aria-label="Loading diff">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <span className="skeleton h-3.5 w-48" />
                {[85, 70, 90, 60, 75].map((w, j) => (
                  <span key={j} className="skeleton h-3" style={{ width: `${w}%` }} />
                ))}
              </div>
            ))}
          </div>
        ) : isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <p className="text-sm text-status-failed">{errorMessage}</p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="rounded border border-status-failed/40 px-3 py-1.5 text-xs text-status-failed hover:bg-status-failed/10 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : data ? (
          <DiffViewer
            diffText={data.diff}
            viewType={viewType}
            filePathFilter={filePath}
            showFileHeaders={false}
            collapsible={false}
          />
        ) : null}
      </div>
    </div>
  );
}
