import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../api/client';
import { useRecoverRun } from '../../hooks/useApi';
import type { RunResponse, TaskStatus } from '../../types';

type TimelineTask = RunResponse['steps'][number]['tasks'][number] & {
  last_status?: string | null;
  end_commit?: string | null;
  attempts_summary?: Array<{
    attempt_num: number;
    outcome: string | null;
    end_commit?: string | null;
  }>;
};

interface RecoveryPanelProps {
  run: RunResponse;
}

function statusClasses(status: TaskStatus | string): string {
  if (status === 'completed') return 'bg-status-completed/15 text-status-completed border-status-completed/35';
  if (status === 'failed') return 'bg-status-failed/15 text-status-failed border-status-failed/35';
  if (status === 'building' || status === 'verifying') {
    return 'bg-accent-purple/15 text-accent-purple border-accent-purple/35';
  }
  return 'bg-bg-elevated text-text-secondary border-border';
}

function readTaskEndCommit(task: TimelineTask): string | null {
  if (typeof task.end_commit === 'string' && task.end_commit.length > 0) {
    return task.end_commit;
  }
  const attempts = task.attempts_summary;
  const lastAttempt = attempts?.[attempts.length - 1];
  if (lastAttempt && typeof lastAttempt.end_commit === 'string' && lastAttempt.end_commit.length > 0) {
    return lastAttempt.end_commit;
  }
  return null;
}

function readTaskLastStatus(task: TimelineTask): string {
  if (typeof task.last_status === 'string' && task.last_status.length > 0) {
    return task.last_status;
  }
  return task.status;
}

export function RecoveryPanel({ run }: RecoveryPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [preserveChecklist, setPreserveChecklist] = useState(false);
  const [recoverError, setRecoverError] = useState<string | null>(null);
  const [successToast, setSuccessToast] = useState<string | null>(null);

  const recoverRun = useRecoverRun(run.id);

  const allTasks = useMemo(
    () => run.steps.flatMap(step => step.tasks as TimelineTask[]),
    [run.steps],
  );

  const selectedTask = useMemo(
    () => allTasks.find(task => task.id === selectedTaskId) ?? null,
    [allTasks, selectedTaskId],
  );

  useEffect(() => {
    if (!successToast) return;
    const timeoutId = window.setTimeout(() => setSuccessToast(null), 3500);
    return () => window.clearTimeout(timeoutId);
  }, [successToast]);

  if (run.status !== 'failed') {
    return null;
  }

  const onOpenConfirm = (taskId: string) => {
    setSelectedTaskId(taskId);
    setPreserveChecklist(false);
    setRecoverError(null);
    setConfirmOpen(true);
  };

  const onCancelConfirm = () => {
    if (recoverRun.isPending) return;
    setConfirmOpen(false);
    setRecoverError(null);
  };

  const onConfirmRecover = () => {
    if (!selectedTaskId) {
      return;
    }

    setRecoverError(null);
    recoverRun.mutate(
      {
        target_task_id: selectedTaskId,
        preserve_checklist: preserveChecklist,
      },
      {
        onSuccess: () => {
          const taskName = selectedTask?.title || selectedTask?.config_id || selectedTaskId;
          setSuccessToast('Recovery started from task "' + taskName + '". Run is now paused.');
          setConfirmOpen(false);
        },
        onError: (error: Error) => {
          if (error instanceof ApiError) {
            setRecoverError(error.message);
            return;
          }
          setRecoverError(error.message || 'Failed to recover run.');
        },
      },
    );
  };

  return (
    <div className="mb-6 rounded-lg border border-status-failed/30 bg-status-failed/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
            Recovery
          </h2>
          <p className="mt-1 text-xs text-text-secondary">
            Select a task to rewind the run and prepare a retry path.
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {run.steps.map((step, stepIndex) => (
          <section key={step.id} className="rounded-md border border-border bg-bg-card p-3">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-bg-elevated text-[10px] font-bold text-text-muted">
                {stepIndex + 1}
              </span>
              <p className="text-sm font-medium text-text-primary">
                {step.title || step.config_id}
              </p>
            </div>

            <div className="space-y-2">
              {step.tasks.map((taskBase, taskIndex) => {
                const task = taskBase as TimelineTask;
                const lastStatus = readTaskLastStatus(task);
                const endCommit = readTaskEndCommit(task);
                return (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => onOpenConfirm(task.id)}
                    className="w-full rounded-md border border-border px-3 py-2 text-left transition-colors hover:bg-bg-hover hover:border-border-hover"
                    aria-label={'Recover to task ' + (task.title || task.config_id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-text-primary">
                          T{taskIndex + 1}: {task.title || task.config_id}
                        </p>
                        <p className="mt-1 text-[11px] font-mono text-text-muted">
                          end_commit: {endCommit ? endCommit.slice(0, 12) : 'not available'}
                        </p>
                      </div>
                      <span className={'rounded border px-2 py-0.5 text-[11px] font-medium ' + statusClasses(lastStatus)}>
                        {lastStatus}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        ))}
      </div>

      {successToast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed right-4 top-4 z-50 rounded-md border border-status-completed/40 bg-status-completed/15 px-3 py-2 text-sm text-status-completed shadow-lg"
        >
          {successToast}
        </div>
      )}

      {confirmOpen && selectedTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onCancelConfirm}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="recover-dialog-title"
            className="mx-4 w-full max-w-md rounded-lg border border-border bg-bg-card p-6 shadow-xl"
            onClick={event => event.stopPropagation()}
          >
            <h3 id="recover-dialog-title" className="text-lg font-semibold text-text-primary">
              Confirm recovery
            </h3>

            <p className="mt-3 text-sm text-text-secondary">
              Selected task: <span className="font-medium text-text-primary">{selectedTask.title || selectedTask.config_id}</span>
            </p>
            <p className="mt-2 text-sm text-status-failed">
              This will reset all downstream tasks to PENDING
            </p>

            <label className="mt-4 flex items-start gap-2 text-sm text-text-secondary">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={preserveChecklist}
                onChange={event => setPreserveChecklist(event.target.checked)}
              />
              <span>preserve_checklist</span>
            </label>

            {recoverError && (
              <p className="mt-3 rounded border border-status-failed/30 bg-status-failed/10 px-2.5 py-2 text-xs text-status-failed">
                {recoverError}
              </p>
            )}

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={onCancelConfirm}
                disabled={recoverRun.isPending}
                className="rounded-md bg-bg-elevated px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirmRecover}
                disabled={recoverRun.isPending}
                className="rounded-md border border-status-failed/40 bg-status-failed/15 px-4 py-2 text-sm font-medium text-status-failed transition-colors hover:bg-status-failed/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {recoverRun.isPending ? 'Recovering...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
