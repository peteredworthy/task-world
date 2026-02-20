import { useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import { useTransitionBack } from '../../hooks/useApi';
import type { StepSummary } from '../../types';
import { getStepState, stepBadgeClasses } from './stepTimelineUtils';

interface StepTimelineProps {
  runId: string;
  steps: StepSummary[];
  currentStepIndex: number;
  showRevert?: boolean;
}

export function StepTimeline({ runId, steps, currentStepIndex, showRevert = false }: StepTimelineProps) {
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [reason, setReason] = useState('');
  const [errorToast, setErrorToast] = useState<string | null>(null);
  const transitionBack = useTransitionBack(runId);

  useEffect(() => {
    if (!errorToast) return;
    const timeoutId = window.setTimeout(() => setErrorToast(null), 3500);
    return () => window.clearTimeout(timeoutId);
  }, [errorToast]);

  function openConfirm(stepIndex: number) {
    setSelectedStepIndex(stepIndex);
    setReason('');
    setErrorToast(null);
  }

  function closeConfirm() {
    if (transitionBack.isPending) return;
    setSelectedStepIndex(null);
    setReason('');
  }

  async function onConfirmRevert() {
    if (selectedStepIndex === null) return;

    try {
      await transitionBack.mutateAsync({
        target_step_index: selectedStepIndex,
        reason: reason.trim() || undefined,
      });
      setSelectedStepIndex(null);
      setReason('');
      setErrorToast(null);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 400) {
          setErrorToast('Invalid step');
          return;
        }
        if (error.status === 409) {
          setErrorToast('Run must be ACTIVE or PAUSED');
          return;
        }
      }
      setErrorToast('Failed to revert step');
    }
  }

  if (steps.length === 0) return null;

  return (
    <>
      <div className="flex items-center gap-1" role="group" aria-label="Step progress">
        {steps.map((step, i) => {
          const total = step.tasks.length;
          const completed = step.tasks.filter(t => t.status === 'completed').length;
          const state = getStepState(step, i === currentStepIndex);
          const canRevert = showRevert && step.completed && i < currentStepIndex;

          return (
            <div key={step.id} className="flex items-center gap-1">
              <div
                className={
                  'flex items-center justify-center rounded font-mono text-[10px] font-bold leading-none ' +
                  'w-7 h-[22px] ' +
                  stepBadgeClasses(state)
                }
                tabIndex={0}
                role="img"
                aria-label={`Step ${i + 1}: ${completed}/${total} tasks, ${state}`}
                title={`Step ${i + 1}: ${completed}/${total} tasks`}
              >
                S{i + 1}
              </div>
              {canRevert && (
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation();
                    openConfirm(i);
                  }}
                  className="rounded border border-status-paused/40 px-2 py-0.5 text-[10px] font-semibold text-status-paused transition-colors hover:bg-status-paused/15"
                  aria-label={`Revert to step ${i + 1}`}
                >
                  Revert to this step
                </button>
              )}
            </div>
          );
        })}
      </div>

      {selectedStepIndex !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={closeConfirm}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="revert-step-dialog-title"
            className="mx-4 w-full max-w-md rounded-lg border border-border bg-bg-card p-6 shadow-xl"
            onClick={event => event.stopPropagation()}
          >
            <h3 id="revert-step-dialog-title" className="text-lg font-semibold text-text-primary">
              Revert to this step?
            </h3>
            <p className="mt-2 text-sm text-status-failed">
              This will reset all tasks from step {selectedStepIndex + 1} onward to PENDING
            </p>
            <div className="mt-4">
              <label htmlFor="revert-reason" className="mb-1 block text-xs font-medium text-text-secondary">
                Reason (optional)
              </label>
              <textarea
                id="revert-reason"
                rows={3}
                value={reason}
                onChange={event => setReason(event.target.value)}
                className="w-full rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                placeholder="Explain why you are reverting this run..."
              />
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeConfirm}
                disabled={transitionBack.isPending}
                className="rounded-md bg-bg-elevated px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirmRevert}
                disabled={transitionBack.isPending}
                className="rounded-md border border-status-paused/40 bg-status-paused/15 px-4 py-2 text-sm font-medium text-status-paused transition-colors hover:bg-status-paused/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {transitionBack.isPending ? 'Reverting...' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}

      {errorToast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed right-4 top-4 z-50 rounded-md border border-status-failed/40 bg-status-failed/15 px-3 py-2 text-sm text-status-failed shadow-lg"
        >
          {errorToast}
        </div>
      )}
    </>
  );
}
