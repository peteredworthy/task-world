import type { StepSummary } from '../../types';

export type StepState = 'completed' | 'active' | 'failed' | 'pending';

export function getStepState(step: StepSummary, isCurrent: boolean): StepState {
  const hasFailed = step.tasks.some(t => t.status === 'failed');
  if (hasFailed) return 'failed';
  if (step.completed) return 'completed';
  if (isCurrent) return 'active';
  return 'pending';
}

export function stepBadgeClasses(state: StepState): string {
  switch (state) {
    case 'completed':
      return 'bg-accent-purple text-white';
    case 'active':
      return 'bg-status-active text-white animate-pulse-glow';
    case 'failed':
      return 'bg-status-failed text-white';
    case 'pending':
      return 'bg-transparent border border-border-hover text-text-muted';
  }
}
