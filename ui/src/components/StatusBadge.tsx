import type { RunStatus, TaskStatus } from '../types';
import { runStatusColor, taskStatusColor } from '../lib/status';

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={'inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ' + runStatusColor(status)}>
      {status}
    </span>
  );
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={'inline-flex items-center rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ' + taskStatusColor(status)}>
      {status}
    </span>
  );
}
