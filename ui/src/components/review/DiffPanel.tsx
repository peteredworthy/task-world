import { useEffect, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import type { ViewType } from 'react-diff-view';
import { ApiError, api } from '../../api/client';
import { useDiff } from '../../hooks/useReview';
import { getTaskDiffFiles } from '../../api/reviewClient';
import { DiffViewer } from './DiffViewer';
import type { RunResponse } from '../../types';

interface DiffPanelProps {
  runId: string;
  filePath: string | null;
  run?: RunResponse;
}

interface TaskOption {
  id: string;
  label: string;
  ref: string | undefined;
}

export function DiffPanel({ runId, filePath, run }: DiffPanelProps) {
  const [selectedOptionId, setSelectedOptionId] = useState<string>('aggregate');
  const [viewType, setViewType] = useState<ViewType>('split');

  // Reset to ALL when a new file is selected
  useEffect(() => {
    if (!filePath) return;
    setSelectedOptionId('aggregate');
  }, [filePath]);

  // Build flat list of tasks with step/task labels
  const flatTasks: { id: string; label: string }[] = (run?.steps ?? []).flatMap((step, si) =>
    step.tasks.map((task) => ({
      id: task.id,
      label: `Step ${si + 1} / ${task.title || task.config_id}`,
    })),
  );

  // Fetch task details for all tasks to get commit ranges
  const taskDetailQueries = useQueries({
    queries: flatTasks.map((t) => ({
      queryKey: ['task', runId, t.id],
      queryFn: () => api.getTask(runId, t.id),
      staleTime: 60_000,
      enabled: !!run,
    })),
  });

  // Build resolved options with commit ranges
  const taskOptions: TaskOption[] = flatTasks.map((t, i) => {
    const detail = taskDetailQueries[i]?.data;
    const lastAttempt = detail?.attempts
      ? [...detail.attempts].sort((a, b) => b.attempt_num - a.attempt_num)[0]
      : undefined;
    const ref =
      lastAttempt?.start_commit && lastAttempt?.end_commit
        ? `${lastAttempt.start_commit}..${lastAttempt.end_commit}`
        : undefined;
    return { id: t.id, label: t.label, ref };
  });

  // Fetch file lists for each task that has a ref, to filter by selected file
  const taskFileQueries = useQueries({
    queries: taskOptions.map((t) => ({
      queryKey: ['taskDiffFiles', runId, t.ref],
      queryFn: () => getTaskDiffFiles(runId, t.ref!),
      staleTime: 60_000,
      enabled: !!t.ref,
    })),
  });

  // Filter tasks to those that touch the selected file (once file lists are loaded)
  const visibleTaskOptions = taskOptions.filter((t, i) => {
    if (!t.ref) return false; // no commits for this task
    if (!filePath) return true; // no file filter — show all
    const files = taskFileQueries[i]?.data;
    if (!files) return true; // still loading — include tentatively
    return files.some((f) => f.path === filePath);
  });

  // Compute scope + ref for useDiff
  const isAggregate = selectedOptionId === 'aggregate';
  const selectedTaskIdx = taskOptions.findIndex((t) => t.id === selectedOptionId);
  const selectedTask = isAggregate ? undefined : taskOptions[selectedTaskIdx];
  const selectedTaskLoading =
    !isAggregate && selectedTaskIdx >= 0 && taskDetailQueries[selectedTaskIdx]?.isLoading === true;

  // If the selected task was filtered out (no changes in this file), reset to aggregate
  const selectedOptionVisible =
    isAggregate || visibleTaskOptions.some((t) => t.id === selectedOptionId);
  useEffect(() => {
    if (!selectedOptionVisible) {
      setSelectedOptionId('aggregate');
    }
  }, [selectedOptionVisible]);

  const diffScope = isAggregate ? 'aggregate' : 'task';
  const diffRef = isAggregate ? undefined : selectedTask?.ref;

  // Only fetch diff when we have what we need
  const diffEnabled = filePath
    ? isAggregate || (selectedTask !== undefined && selectedTask.ref !== undefined)
    : true;

  const { data, isLoading, isError, error, refetch } = useDiff(
    diffEnabled && filePath ? runId : undefined,
    diffScope,
    diffRef,
  );

  const errorMessage = error instanceof ApiError ? error.message : 'Failed to load diff.';

  return (
    <div className="flex h-full min-h-0 flex-col rounded-md border border-border-hover bg-bg-elevated">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border-hover px-4 py-3">
        <div className="min-w-0 flex-1">
          {filePath ? (
            <>
              <p className="truncate font-mono text-xs text-text-primary" title={filePath}>
                {filePath}
              </p>
              <p className="mt-0.5 text-[11px] text-text-muted">Review selected file diff</p>
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

        {/* Commit scope dropdown */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="diff-commit-select" className="text-xs text-text-muted shrink-0">
            Commit
          </label>
          <select
            id="diff-commit-select"
            value={selectedOptionId}
            onChange={(e) => setSelectedOptionId(e.target.value)}
            disabled={!filePath}
            className="rounded border border-border-hover bg-bg-card px-2 py-1 text-xs text-text-primary max-w-[220px] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="aggregate">ALL</option>
            {visibleTaskOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Inline / Split sliding toggle — matches Agent Log style in TaskDetailCard */}
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
        ) : !isAggregate && selectedTask !== undefined && selectedTask.ref === undefined && selectedTaskLoading ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">Loading task data…</p>
          </div>
        ) : !isAggregate && selectedTask !== undefined && selectedTask.ref === undefined ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-text-muted">No commit range available for this task.</p>
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
