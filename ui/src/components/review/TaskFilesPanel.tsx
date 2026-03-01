import { useState } from 'react';
import { useTask } from '../../hooks/useApi';
import { useTaskDiffFiles } from '../../hooks/useReview';
import { DiffDialog } from './DiffDialog';
import type { RunResponse, TaskSummary } from '../../types';

const FILE_COLLAPSE_THRESHOLD = 8;

interface TaskFilesPanelProps {
  runId: string;
  run: RunResponse;
}

interface DiffTarget {
  filePath: string;
  taskRef: string;
}

function TaskCard({
  runId,
  task,
  onViewDiff,
}: {
  runId: string;
  task: TaskSummary;
  onViewDiff: (filePath: string, taskRef: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: taskDetail } = useTask(runId, task.id);

  // Use the last attempt's commit range
  const lastAttempt = taskDetail?.attempts
    ? [...taskDetail.attempts].sort((a, b) => b.attempt_num - a.attempt_num)[0]
    : undefined;

  const taskRef =
    lastAttempt?.start_commit && lastAttempt?.end_commit
      ? `${lastAttempt.start_commit}..${lastAttempt.end_commit}`
      : undefined;

  const { data: files, isLoading, isError } = useTaskDiffFiles(
    taskRef ? runId : undefined,
    taskRef,
  );

  const fileCount = files?.length ?? 0;
  const collapseByDefault = fileCount > FILE_COLLAPSE_THRESHOLD;
  const showFiles = expanded || !collapseByDefault;

  if (!taskRef && taskDetail) {
    // Task detail loaded but no commit range
    return (
      <div className="rounded border border-border bg-bg-elevated p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-text-primary" title={task.title}>
              {task.title || task.config_id}
            </p>
            <p className="text-[10px] text-text-muted">{task.id.slice(0, 8)}</p>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-text-muted italic">No changes recorded</p>
      </div>
    );
  }

  return (
    <div className="rounded border border-border bg-bg-elevated">
      {/* Card header */}
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-text-primary" title={task.title}>
            {task.title || task.config_id}
          </p>
          <p className="text-[10px] text-text-muted">{task.id.slice(0, 8)}</p>
        </div>

        {isLoading ? (
          <span className="shrink-0 text-[10px] text-text-muted">Loading…</span>
        ) : isError ? (
          <span className="shrink-0 text-[10px] text-status-failed">Error</span>
        ) : files !== undefined ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="shrink-0 flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-text-muted hover:bg-bg-muted hover:text-text-secondary transition-colors"
          >
            <span>Files touched ({fileCount})</span>
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="none"
              className={`transition-transform ${showFiles ? 'rotate-180' : ''}`}
            >
              <path
                d="M2 3.5L5 6.5L8 3.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        ) : null}
      </div>

      {/* File list */}
      {showFiles && files && files.length > 0 && taskRef && (
        <div className="border-t border-border px-3 py-2">
          <div className="flex flex-col gap-1">
            {files.map((file) => (
              <div key={file.path} className="flex items-center gap-2 min-w-0">
                <span
                  className="flex-1 truncate font-mono text-[11px] text-text-secondary"
                  title={file.path}
                >
                  {file.path}
                </span>
                <button
                  type="button"
                  onClick={() => onViewDiff(file.path, taskRef)}
                  className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium text-blue-400 hover:bg-blue-500/10 transition-colors"
                >
                  View Diff
                </button>
              </div>
            ))}
          </div>
          {collapseByDefault && !expanded && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="mt-1 text-[10px] text-text-muted hover:text-text-secondary transition-colors"
            >
              Show all {fileCount} files…
            </button>
          )}
        </div>
      )}

      {showFiles && files && files.length === 0 && (
        <div className="border-t border-border px-3 py-2">
          <p className="text-[11px] text-text-muted italic">No files modified</p>
        </div>
      )}
    </div>
  );
}

export function TaskFilesPanel({ runId, run }: TaskFilesPanelProps) {
  const [diffTarget, setDiffTarget] = useState<DiffTarget | null>(null);

  const allTasks: TaskSummary[] = run.steps.flatMap((step) => step.tasks);

  const handleViewDiff = (filePath: string, taskRef: string) => {
    setDiffTarget({ filePath, taskRef });
  };

  return (
    <div className="rounded-md border border-border bg-bg-elevated p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
        Task Files
        {allTasks.length > 0 && (
          <span className="ml-1.5 font-normal text-text-muted">({allTasks.length})</span>
        )}
      </h3>

      <div className="mt-3">
        {allTasks.length === 0 ? (
          <p className="text-xs text-text-muted">No task data available.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {allTasks.map((task) => (
              <TaskCard
                key={task.id}
                runId={runId}
                task={task}
                onViewDiff={handleViewDiff}
              />
            ))}
          </div>
        )}
      </div>

      {diffTarget && (
        <DiffDialog
          runId={runId}
          filePath={diffTarget.filePath}
          isOpen={true}
          onClose={() => setDiffTarget(null)}
          initialScope="task"
          initialRef={diffTarget.taskRef}
        />
      )}
    </div>
  );
}
