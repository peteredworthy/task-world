import type { Priority } from '../types';
import { priorityColor } from '../lib/status';

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ' + priorityColor(priority)}>
      {priority}
    </span>
  );
}
