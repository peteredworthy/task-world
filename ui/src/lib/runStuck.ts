import type { RunResponse } from '../types';

export function isRunStuck(run: RunResponse): { stuck: boolean; failedTask: string | null } {
  if (run.status !== 'active') return { stuck: false, failedTask: null };
  for (const step of run.steps) {
    const failed = step.tasks.find(
      t => !t.parent_task_id && t.status === 'failed' && t.current_attempt >= t.max_attempts,
    );
    if (failed) {
      return { stuck: true, failedTask: failed.title || failed.config_id };
    }
  }
  return { stuck: false, failedTask: null };
}
