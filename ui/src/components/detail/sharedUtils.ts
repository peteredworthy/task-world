import type { AttemptSchema, TaskStatus } from '../../types';

/** Returns true if a grade + priority combination caused a verification failure. */
export function isGradeFailing(grade: string | null | undefined, priority: string): boolean {
  if (!grade) return priority === 'critical' || priority === 'expected';
  if (priority === 'critical') return grade !== 'A';
  if (priority === 'expected') return grade !== 'A' && grade !== 'B';
  return false;
}

export function getMetric(metrics: Record<string, unknown>, key: string): number {
  const v = metrics[key];
  return typeof v === 'number' ? v : 0;
}

export const PRIORITY_ORDER = ['critical', 'expected', 'nice'] as const;

export const PRIORITY_LABELS: Record<string, string> = {
  critical: 'Required',
  expected: 'Expected',
  nice: 'Optional',
};

// Shared visual token for collapsible containers/headers so outlines stay uniform.
export const COLLAPSIBLE_BORDER_CLASS = 'border-border-hover';
export const COLLAPSIBLE_DIVIDER_CLASS = 'border-border-hover';

interface LatestAttemptContext {
  latest: AttemptSchema | null;
  isActiveAttempt: boolean;
  hasError: boolean;
  hasAutoVerify: boolean;
  hasAutoVerifyFailure: boolean;
  hasFailure: boolean;
  showFailureCard: boolean;
  showFeedbackCard: boolean;
  feedbackTitle: 'Auto-verify Feedback' | 'Verifier Feedback';
}

const IN_PROGRESS_TASK_STATUSES = new Set<TaskStatus>(['building', 'verifying', 'fan_out_running']);

export function getLatestAttemptContext(
  attempts: AttemptSchema[],
  taskStatus: TaskStatus,
): LatestAttemptContext {
  const latest = attempts.length > 0 ? attempts[attempts.length - 1] : null;
  const hasError = Boolean(latest?.error);
  const hasAutoVerify = Boolean(latest?.auto_verify_results && latest.auto_verify_results.length > 0);
  const hasAutoVerifyFailure =
    hasAutoVerify && (latest?.auto_verify_results?.some(result => !result.passed) ?? false);
  const hasFailure = hasError || hasAutoVerifyFailure || latest?.outcome === 'failed';
  const isActiveAttempt = Boolean(
    latest
    && latest.completed_at === null
    && IN_PROGRESS_TASK_STATUSES.has(taskStatus),
  );

  const comment = latest?.verifier_comment ?? '';
  const isAutoVerifyFeedback = Boolean(
    comment
    && hasAutoVerifyFailure
    && comment.toLowerCase().includes('auto-verify'),
  );

  return {
    latest,
    isActiveAttempt,
    hasError,
    hasAutoVerify,
    hasAutoVerifyFailure,
    hasFailure,
    showFailureCard: hasFailure && !isActiveAttempt,
    showFeedbackCard: Boolean(comment) && (!isActiveAttempt || taskStatus === 'recovering'),
    feedbackTitle: isAutoVerifyFeedback ? 'Auto-verify Feedback' : 'Verifier Feedback',
  };
}
