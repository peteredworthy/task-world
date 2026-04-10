import { formatRelativeTime } from '../../lib/format';
import type { ActivityEvent } from '../../types';

interface ActivityFeedProps {
  events: ActivityEvent[];
}

function eventLabel(eventType: string, payload: Record<string, unknown>): string {
  switch (eventType) {
    case 'task_status_changed': {
      const oldS = payload.old_status as string | undefined;
      const newS = payload.new_status as string | undefined;
      if (oldS && newS) return `${oldS} → ${newS}`;
      return 'status changed';
    }
    case 'run_status_changed': {
      const oldS = payload.old_status as string | undefined;
      const newS = payload.new_status as string | undefined;
      if (oldS && newS) {
        return `Run ${oldS} → ${newS}`;
      }
      if (newS) {
        return `Run ${newS}`;
      }
      return 'Run status changed';
    }
    case 'checklist_gate_evaluated':
      return payload.passed ? 'Gate passed' : 'Gate blocked';
    case 'grades_evaluated':
      return payload.passed ? 'Grades passed' : 'Grades failed';
    case 'step_completed':
      return 'Step completed';
    case 'step_skipped': {
      const reason = payload.skip_reason as string | undefined;
      return reason ? `Skipped: ${reason}` : 'Step skipped';
    }
    case 'agent_error':
      return (payload.error_message as string) || 'Agent error';
    default:
      return eventType.replace(/_/g, ' ');
  }
}

function eventDotColor(eventType: string): string {
  switch (eventType) {
    case 'step_skipped':
      return 'bg-status-paused';
    case 'agent_error':
      return 'bg-status-failed';
    default:
      return 'bg-border';
  }
}

export function ActivityFeed({ events }: ActivityFeedProps) {
  if (events.length === 0) {
    return (
      <div className="text-center py-4 text-text-muted text-xs">
        No activity yet
      </div>
    );
  }

  return (
    <div className="space-y-2" role="feed" aria-label="Activity log">
      {events.map((event) => {
        const isError = event.event_type === 'agent_error';
        const isSkipped = event.event_type === 'step_skipped';
        return (
          <div key={event.id} className="flex items-center gap-2 text-xs px-2 py-1">
            <span className={'w-1.5 h-1.5 rounded-full shrink-0 ' + eventDotColor(event.event_type)} />
            <span className={isError || isSkipped ? (isError ? 'text-status-failed font-medium' : 'text-status-paused font-medium') : 'text-text-secondary'}>
              {eventLabel(event.event_type, event.payload)}
            </span>
            <span className="text-text-muted ml-auto text-[10px] whitespace-nowrap">
              {formatRelativeTime(event.timestamp)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
