import type { RunStatus, TaskStatus } from '../types';
import { runStatusColor, taskStatusColor } from '../lib/status';

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={'inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ' + runStatusColor(status)}>
      {status}
    </span>
  );
}

const TASK_STATUS_LABELS: Partial<Record<TaskStatus, string>> = {
  fan_out_running: 'Fan-out',
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const label = TASK_STATUS_LABELS[status] ?? status;
  return (
    <span className={'inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ' + taskStatusColor(status)}>
      {label}
    </span>
  );
}
