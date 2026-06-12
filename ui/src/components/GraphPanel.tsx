import { useMemo, useState } from 'react';
import { useGraphEvents, useGraphProjection } from '../hooks/useApi';
import type { GraphEventResponse, GraphProjectionResponse, RunResponse } from '../types';

interface GraphPanelProps {
  runId: string;
  run: RunResponse;
  open: boolean;
  onClose: () => void;
}

function runStateChipClass(runState: string | null): string {
  if (!runState) {
    return 'bg-bg-muted text-text-muted';
  }
  if (runState === 'failed') {
    return 'bg-status-failed/15 text-status-failed';
  }
  if (runState === 'completed') {
    return 'bg-status-completed/15 text-status-completed';
  }
  return 'bg-accent-cyan/15 text-accent-cyan';
}

function NodeStatesTable({ projection }: { projection: GraphProjectionResponse }) {
  const rows = useMemo(() => {
    const leases = Object.values(projection.leases);
    return Object.entries(projection.node_states)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([nodeId, state]) => {
        const lease = leases.find((entry) => entry.node_id === nodeId && entry.state === 'active')
          ?? leases.find((entry) => entry.node_id === nodeId);
        return {
          nodeId,
          state,
          leaseId: lease?.lease_id ?? null,
          leaseState: lease?.state ?? null,
        };
      });
  }, [projection.leases, projection.node_states]);

  return (
    <div>
      <h3 className="text-sm font-semibold text-text-primary mb-2">Node states</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-xs">
          <thead className="text-text-muted">
            <tr>
              <th className="pr-3 pb-1">node_id</th>
              <th className="pr-3 pb-1">state</th>
              <th className="pb-1">lease</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={3} className="py-2 text-text-muted italic">
                  No node state records yet
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.nodeId} className="border-t border-border/80">
                  <td className="py-2 pr-3 font-mono text-text-primary break-all">{row.nodeId}</td>
                  <td className="py-2 pr-3">
                    <span className="inline-flex rounded border border-border bg-bg-card px-1.5 py-0.5 text-[10px] text-text-muted">
                      {row.state}
                    </span>
                  </td>
                  <td className="py-2 text-text-secondary">
                    {row.leaseId ? `${row.leaseId} (${row.leaseState})` : '-'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TaskStatesSection({ projection, run }: { projection: GraphProjectionResponse; run: RunResponse }) {
  const rows = useMemo(() => {
    const tasks: Array<{ taskId: string; title: string; taskState: string }> = [];
    for (const step of run.steps) {
      for (const task of step.tasks) {
        const taskState = projection.task_states[task.id];
        if (taskState) {
          tasks.push({ taskId: task.id, title: task.title || task.config_id, taskState });
        }
      }
    }
    return tasks;
  }, [projection.task_states, run.steps]);

  return (
    <div>
      <h3 className="text-sm font-semibold text-text-primary mb-2">Task states</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-text-muted italic">No task states yet</p>
      ) : (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li key={row.taskId} className="flex items-center justify-between gap-3 rounded border border-border bg-bg-card px-2 py-1 text-xs">
              <span className="truncate text-text-primary" title={row.title}>{row.taskId}</span>
              <span className="text-text-muted shrink-0">{row.taskState}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EventModal({
  events,
  onClose,
}: {
  events: GraphEventResponse[];
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-4xl border border-border bg-bg-elevated rounded-lg shadow-xl max-h-[85vh] overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-text-primary">Graph Events</h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors"
            aria-label="Close events modal"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="p-4 overflow-auto" style={{ maxHeight: 'calc(85vh - 56px)' }}>
          {events.length === 0 ? (
            <p className="text-sm text-text-muted">No events yet.</p>
          ) : (
            <pre className="rounded border border-border bg-bg-card p-3 text-xs text-text-secondary overflow-auto">
              {events.map(event => JSON.stringify(event, null, 2)).join('\n\n')}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

export function GraphPanel({ runId, run, open, onClose }: GraphPanelProps) {
  const { data: projection } = useGraphProjection(runId);
  const { data: events = [] } = useGraphEvents(runId);
  const [showEvents, setShowEvents] = useState(false);

  if (!open || !projection) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 pointer-events-none">
      <div className="absolute inset-0 bg-black/60 pointer-events-auto" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 w-full max-w-lg border-l border-border bg-bg-elevated pointer-events-auto p-4 overflow-y-auto animate-slide-in-right">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Graph projection</h2>
            <p className="text-xs text-text-muted mt-1 break-all">{runId}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:bg-bg-hover hover:text-text-primary transition-colors"
            aria-label="Close graph panel"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <span className={`inline-flex rounded px-2 py-0.5 text-xs font-semibold ${runStateChipClass(projection.run_state)}`}>
            {projection.run_state ?? 'not_started'}
          </span>
          <span className="text-xs text-text-muted">
            event_count: {projection.event_count}
          </span>
        </div>

        <div className="mt-4 space-y-4">
          <NodeStatesTable projection={projection} />
          <TaskStatesSection projection={projection} run={run} />
          <button
            type="button"
            onClick={() => setShowEvents(true)}
            className="text-xs text-accent-purple hover:text-accent-purple/80 underline decoration-dotted"
          >
            Events ({events.length})
          </button>
        </div>
      </aside>
      {showEvents && <EventModal events={events} onClose={() => setShowEvents(false)} />}
    </div>
  );
}
