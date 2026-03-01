import { useState, useEffect, useMemo } from 'react';
import type { ViewType } from 'react-diff-view';
import { parseDiff } from 'react-diff-view';
import { useDiff, useCommits } from '../../hooks/useReview';
import { ApiError } from '../../api/client';
import { DiffViewer } from './DiffViewer';

const LARGE_DIFF_THRESHOLD = 1000;

type DiffScope = 'aggregate' | 'commit' | 'task';

interface DiffDialogProps {
  runId: string;
  filePath: string;
  isOpen: boolean;
  onClose: () => void;
  initialScope?: DiffScope;
  initialRef?: string;
}

export function DiffDialog({ runId, filePath, isOpen, onClose, initialScope, initialRef }: DiffDialogProps) {
  const [scope, setScope] = useState<DiffScope>(initialScope ?? 'aggregate');
  const [viewType, setViewType] = useState<ViewType>('unified');
  const [selectedRef, setSelectedRef] = useState<string | undefined>(initialRef);
  const [expandAllSignal, setExpandAllSignal] = useState(0);
  const [collapseAllSignal, setCollapseAllSignal] = useState(0);

  const { data: commits } = useCommits(scope === 'commit' ? runId : undefined);

  const { data, isLoading, isError, error, refetch } = useDiff(
    isOpen ? runId : undefined,
    scope,
    selectedRef,
  );

  // Detect whether the loaded diff has any large file sections
  const hasLargeFiles = useMemo(() => {
    if (!data?.diff) return false;
    try {
      const parsed = parseDiff(data.diff);
      return parsed.some(
        (file) => file.hunks.reduce((sum, h) => sum + h.changes.length, 0) > LARGE_DIFF_THRESHOLD,
      );
    } catch {
      return false;
    }
  }, [data]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  // Reset scope/ref when dialog opens with a new file or new initial values
  useEffect(() => {
    if (isOpen) {
      setScope(initialScope ?? 'aggregate');
      setSelectedRef(initialRef);
      // Reset expand/collapse signals when the dialog reopens
      setExpandAllSignal(0);
      setCollapseAllSignal(0);
    }
  }, [isOpen, filePath, initialScope, initialRef]);

  if (!isOpen) return null;

  const errorMessage = error instanceof ApiError ? error.message : 'Failed to load diff.';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />

      {/* Dialog — full width/height on mobile, constrained on larger screens */}
      <div className="relative z-10 flex flex-col w-full h-full sm:w-[95vw] sm:h-[90vh] sm:rounded-lg border border-border bg-bg-primary shadow-xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0 border-b border-border bg-bg-elevated px-3 sm:px-4 py-2 sm:py-3">
          <span className="flex-1 truncate font-mono text-sm text-text-primary" title={filePath}>
            {filePath}
          </span>

          {/* Expand/Collapse All controls — shown when data is loaded and has large files */}
          {data && hasLargeFiles && (
            <div className="flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
              <button
                type="button"
                onClick={() => setExpandAllSignal((s) => s + 1)}
                className="rounded px-2.5 py-1 text-xs text-text-muted hover:text-text-secondary transition-colors"
                title="Expand all file sections"
              >
                Expand All
              </button>
              <button
                type="button"
                onClick={() => setCollapseAllSignal((s) => s + 1)}
                className="rounded px-2.5 py-1 text-xs text-text-muted hover:text-text-secondary transition-colors"
                title="Collapse all file sections"
              >
                Collapse All
              </button>
            </div>
          )}

          {/* Scope selector */}
          <div className="flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
            {(['aggregate', 'commit', 'task'] as DiffScope[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  setScope(s);
                  setSelectedRef(s === 'task' ? initialRef : undefined);
                }}
                className={`rounded px-2.5 py-1 text-xs capitalize transition-colors ${
                  scope === s
                    ? 'bg-bg-elevated text-text-primary shadow-sm'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* View mode toggle */}
          <div className="flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
            <button
              type="button"
              onClick={() => setViewType('unified')}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                viewType === 'unified'
                  ? 'bg-bg-elevated text-text-primary shadow-sm'
                  : 'text-text-muted hover:text-text-secondary'
              }`}
            >
              Inline
            </button>
            <button
              type="button"
              onClick={() => setViewType('split')}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                viewType === 'split'
                  ? 'bg-bg-elevated text-text-primary shadow-sm'
                  : 'text-text-muted hover:text-text-secondary'
              }`}
            >
              Split
            </button>
          </div>

          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors"
            aria-label="Close diff dialog"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Commit selector (when scope === 'commit') */}
        {scope === 'commit' && (
          <div className="shrink-0 border-b border-border bg-bg-elevated px-4 py-2">
            <select
              value={selectedRef ?? ''}
              onChange={(e) => setSelectedRef(e.target.value || undefined)}
              className="w-full max-w-xs rounded border border-border bg-bg-muted px-2 py-1 text-xs text-text-primary"
            >
              <option value="">Select a commit…</option>
              {commits?.map((commit) => (
                <option key={commit.sha} value={commit.sha}>
                  {commit.short_sha} — {commit.message}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Content area */}
        <div className="flex-1 min-h-0 overflow-auto p-4">
          {scope === 'commit' && !selectedRef ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-text-muted">Select a commit to view its diff.</p>
            </div>
          ) : scope === 'task' && !selectedRef ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-text-muted">No task commit range available.</p>
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
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <p className="text-sm text-status-failed">{errorMessage}</p>
              <button
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
              expandAllSignal={expandAllSignal}
              collapseAllSignal={collapseAllSignal}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
