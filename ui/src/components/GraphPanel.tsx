import { useEffect, useMemo, useState } from 'react';
import { useDecisionView, useFileStateReport, useGraphEvents, useGraphProjection, useSchedulerView } from '../hooks/useApi';
import { FileStateViewer } from './FileStateViewer';
import { NodeDetailPanel } from './NodeDetailPanel';
import { SchedulerView } from './SchedulerView';
import type { ActivityEvent, DecisionViewResponse, GraphEventResponse, GraphProjectionResponse, RunResponse, SchedulerViewResponse } from '../types';

interface GraphPanelProps {
  runId: string;
  run: RunResponse;
  open: boolean;
  onClose: () => void;
  activityEvents?: ActivityEvent[];
  initialNodeId?: string | null;
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

function payloadText(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function payloadTextList(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

function payloadGrades(payload: Record<string, unknown>): Array<{ requirementId: string | null; grade: string | null }> {
  const rawGrades = payload.grades;
  if (!Array.isArray(rawGrades)) return [];
  return rawGrades
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object' && !Array.isArray(entry))
    .map((entry) => ({
      requirementId: payloadText(entry, 'requirement_id'),
      grade: payloadText(entry, 'grade'),
    }));
}

function GraphSummaryMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded border border-border bg-bg-card px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-normal text-text-muted">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}

function graphActivityKind(event: ActivityEvent): 'patch' | 'verifier' | 'blocker' | null {
  if (event.event_type === 'graph_patch_accepted' || event.event_type === 'graph_patch_rejected') return 'patch';
  if (event.event_type === 'verification_passed' || event.event_type === 'verification_failed') return 'verifier';
  if (event.event_type === 'command_rejected' || event.event_type === 'node_deferred') return 'blocker';
  if (event.event_type === 'node_created') {
    const summary = payloadText(event.payload, 'summary');
    const kind = payloadText(event.payload, 'kind');
    return kind === 'review' || summary?.startsWith('Graph final invariant blocked') ? 'blocker' : null;
  }
  return null;
}

function OperatorSummary({
  projection,
  schedulerView,
  decisionView,
  activityEvents,
}: {
  projection: GraphProjectionResponse;
  schedulerView?: SchedulerViewResponse;
  decisionView?: DecisionViewResponse;
  activityEvents: ActivityEvent[];
}) {
  const activityCounts = useMemo(() => {
    let patchesAccepted = 0;
    let patchesRejected = 0;
    let verifierPassed = 0;
    let verifierFailed = 0;
    let blockers = 0;
    for (const event of activityEvents) {
      if (event.event_type === 'graph_patch_accepted') patchesAccepted += 1;
      if (event.event_type === 'graph_patch_rejected') patchesRejected += 1;
      if (event.event_type === 'verification_passed') verifierPassed += 1;
      if (event.event_type === 'verification_failed') verifierFailed += 1;
      if (graphActivityKind(event) === 'blocker') blockers += 1;
    }
    return { patchesAccepted, patchesRejected, verifierPassed, verifierFailed, blockers };
  }, [activityEvents]);

  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">Operator summary</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <GraphSummaryMetric label="Graph state" value={projection.run_state ?? 'not started'} />
        <GraphSummaryMetric label="Events" value={projection.event_count} />
        <GraphSummaryMetric label="Ready" value={schedulerView?.scheduler.ready.length ?? 0} />
        <GraphSummaryMetric label="Blocked" value={schedulerView?.scheduler.blocked.length ?? 0} />
        <GraphSummaryMetric label="Waiting resources" value={schedulerView?.scheduler.waiting_resources.length ?? 0} />
        <GraphSummaryMetric label="Waiting gates" value={schedulerView?.scheduler.waiting_gates.length ?? 0} />
        <GraphSummaryMetric label="Active leases" value={schedulerView?.leases.active.length ?? 0} />
        <GraphSummaryMetric label="Suspended leases" value={schedulerView?.leases.suspended.length ?? 0} />
        <GraphSummaryMetric label="Human gates" value={decisionView?.pending_gates.length ?? 0} />
        <GraphSummaryMetric label="Appeals" value={decisionView?.appeals.length ?? 0} />
        <GraphSummaryMetric label="Review blockers" value={decisionView?.review.blockers.length ?? 0} />
        <GraphSummaryMetric label="Patches accepted" value={activityCounts.patchesAccepted} />
        <GraphSummaryMetric label="Patches rejected" value={activityCounts.patchesRejected} />
        <GraphSummaryMetric label="Verifier pass/fail" value={`${activityCounts.verifierPassed}/${activityCounts.verifierFailed}`} />
        <GraphSummaryMetric label="Activity blockers" value={activityCounts.blockers} />
      </div>
    </section>
  );
}

function GraphActivitySection({ activityEvents }: { activityEvents: ActivityEvent[] }) {
  const rows = useMemo(() => {
    const patchRows: ActivityEvent[] = [];
    const verifierRows: ActivityEvent[] = [];
    const blockerRows: ActivityEvent[] = [];
    for (const event of activityEvents) {
      const kind = graphActivityKind(event);
      if (kind === 'patch') patchRows.push(event);
      if (kind === 'verifier') verifierRows.push(event);
      if (kind === 'blocker') blockerRows.push(event);
    }
    return {
      patchRows: patchRows.slice(-8).reverse(),
      verifierRows: verifierRows.slice(-8).reverse(),
      blockerRows: blockerRows.slice(-8).reverse(),
    };
  }, [activityEvents]);

  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">Graph activity</h3>
      <div className="space-y-3 text-xs">
        <PatchActivityList events={rows.patchRows} />
        <VerifierActivityList events={rows.verifierRows} />
        <BlockerActivityList events={rows.blockerRows} />
      </div>
    </section>
  );
}

function PatchActivityList({ events }: { events: ActivityEvent[] }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium text-text-primary">Patch decisions</span>
        <span className="text-text-muted">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <p className="text-text-muted italic">No patch decisions yet</p>
      ) : (
        <ul className="space-y-1">
          {events.map((event) => {
            const payload = event.payload;
            const accepted = event.event_type === 'graph_patch_accepted';
            const successors = payloadTextList(payload, 'successor_planner_node_ids');
            return (
              <li key={event.id} className="rounded border border-border/80 bg-bg-card px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={accepted ? 'font-medium text-status-completed' : 'font-medium text-status-failed'}>
                    {accepted ? 'accepted' : 'rejected'}
                  </span>
                  <span className="font-mono text-[11px] text-text-muted">{payloadText(payload, 'patch_id') ?? `event-${event.id}`}</span>
                </div>
                <div className="mt-1 text-text-secondary">
                  proposer {payloadText(payload, 'proposed_by_node_id') ?? '-'} · actor {payloadText(payload, 'actor_role') ?? '-'}
                </div>
                {payloadText(payload, 'reason') && <div className="mt-1 text-text-muted">reason: {payloadText(payload, 'reason')}</div>}
                {successors.length > 0 && <div className="mt-1 text-text-muted">successors: {successors.join(', ')}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function VerifierActivityList({ events }: { events: ActivityEvent[] }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium text-text-primary">Verifier results</span>
        <span className="text-text-muted">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <p className="text-text-muted italic">No verifier results yet</p>
      ) : (
        <ul className="space-y-1">
          {events.map((event) => {
            const payload = event.payload;
            const verdict = payloadText(payload, 'verdict') ?? (event.event_type === 'verification_passed' ? 'passed' : 'failed');
            const grades = payloadGrades(payload);
            const nonA = grades.filter((grade) => grade.grade && grade.grade !== 'A');
            const requirementText = nonA.length > 0
              ? nonA.map((grade) => `${grade.requirementId ?? 'requirement'}=${grade.grade}`).join(', ')
              : grades.length > 0
                ? 'all A'
                : '-';
            return (
              <li key={event.id} className="rounded border border-border/80 bg-bg-card px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={verdict === 'passed' ? 'font-medium text-status-completed' : 'font-medium text-status-failed'}>
                    {verdict}
                  </span>
                  <span className="font-mono text-[11px] text-text-muted">{payloadText(payload, 'candidate_id') ?? `event-${event.id}`}</span>
                </div>
                <div className="mt-1 text-text-secondary">task {payloadText(payload, 'task_region_id') ?? '-'}</div>
                <div className="mt-1 text-text-muted">requirements: {requirementText}</div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function BlockerActivityList({ events }: { events: ActivityEvent[] }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium text-text-primary">Commands and blockers</span>
        <span className="text-text-muted">{events.length}</span>
      </div>
      {events.length === 0 ? (
        <p className="text-text-muted italic">No command rejections or blockers yet</p>
      ) : (
        <ul className="space-y-1">
          {events.map((event) => {
            const payload = event.payload;
            const node = payloadText(payload, 'node_id') ?? payloadText(payload, 'command_type') ?? `event-${event.id}`;
            return (
              <li key={event.id} className="rounded border border-border/80 bg-bg-card px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-text-primary">{event.event_type}</span>
                  <span className="font-mono text-[11px] text-text-muted">{node}</span>
                </div>
                <div className="mt-1 break-words text-text-muted">
                  {payloadText(payload, 'reason') ?? payloadText(payload, 'summary') ?? 'no reason recorded'}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function NodeStatesTable({
  projection,
  events,
  activityEvents,
  selectedNodeId,
  onSelectNode,
}: {
  projection: GraphProjectionResponse;
  events: GraphEventResponse[];
  activityEvents: ActivityEvent[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const nodeActivity = useMemo(() => {
    const nodeTaskKeys = new Map<string, Set<string>>();
    for (const event of events) {
      if (event.event_type !== 'node_created') continue;
      const nodeId = event.payload.node_id;
      if (typeof nodeId !== 'string') continue;
      const keys = new Set<string>([nodeId]);
      for (const field of ['task_id', 'task_region_id']) {
        const value = event.payload[field];
        if (typeof value === 'string' && value.length > 0) keys.add(value);
      }
      nodeTaskKeys.set(nodeId, keys);
    }

    const latestByNode = new Map<string, string>();
    for (const event of activityEvents) {
      if (event.event_type !== 'agent_output') continue;
      const taskId = event.payload.task_id;
      const lines = event.payload.lines;
      if (typeof taskId !== 'string' || !Array.isArray(lines) || lines.length === 0) continue;
      const latestLine = String(lines[lines.length - 1]);
      for (const [nodeId, keys] of nodeTaskKeys) {
        if (keys.has(taskId)) latestByNode.set(nodeId, latestLine);
      }
    }
    return latestByNode;
  }, [activityEvents, events]);

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
          latestOutput: nodeActivity.get(nodeId) ?? null,
        };
      });
  }, [nodeActivity, projection.leases, projection.node_states]);

  return (
    <div>
      <h3 className="text-sm font-semibold text-text-primary mb-2">Node states</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-xs">
          <thead className="text-text-muted">
            <tr>
              <th className="pr-3 pb-1">node_id</th>
              <th className="pr-3 pb-1">state</th>
              <th className="pr-3 pb-1">lease</th>
              <th className="pb-1">live activity</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-2 text-text-muted italic">
                  No node state records yet
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={row.nodeId}
                  className={'border-t border-border/80 ' + (selectedNodeId === row.nodeId ? 'bg-accent-purple/10' : '')}
                >
                  <td className="py-2 pr-3">
                    <button
                      type="button"
                      onClick={() => onSelectNode(row.nodeId)}
                      className="break-all text-left font-mono text-text-primary underline decoration-dotted hover:text-accent-purple"
                    >
                      {row.nodeId}
                    </button>
                  </td>
                  <td className="py-2 pr-3">
                    <span className="inline-flex rounded border border-border bg-bg-card px-1.5 py-0.5 text-[10px] text-text-muted">
                      {row.state}
                    </span>
                  </td>
                  <td className="py-2 text-text-secondary">
                    {row.leaseId ? `${row.leaseId} (${row.leaseState})` : '-'}
                  </td>
                  <td className="py-2 text-text-secondary">
                    {row.latestOutput ? (
                      <span className="block max-w-[12rem] truncate font-mono text-[11px]" title={row.latestOutput}>
                        {row.latestOutput}
                      </span>
                    ) : (
                      <span className="text-text-muted">-</span>
                    )}
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

function DecisionsSection({ view }: { view: DecisionViewResponse }) {
  const reviewLabel = view.review.ready ? 'Ready' : 'Blocked';
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">Decisions</h3>
      <div className="space-y-3 rounded border border-border bg-bg-card p-3 text-xs">
        <div>
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="font-medium text-text-primary">Pending gates</span>
            <span className="text-text-muted">{view.pending_gates.length}</span>
          </div>
          {view.pending_gates.length === 0 ? (
            <p className="text-text-muted italic">No pending human gates</p>
          ) : (
            <ul className="space-y-1">
              {view.pending_gates.map((gate) => (
                <li key={gate.node_id} className="rounded border border-border/80 bg-bg-elevated px-2 py-1.5">
                  <div className="break-all font-mono text-text-primary">{gate.node_id}</div>
                  <div className="mt-1 text-text-muted">{gate.gate_type}</div>
                  {gate.prompt && <div className="mt-1 text-text-secondary">{gate.prompt}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="font-medium text-text-primary">Appeals</span>
            <span className="text-text-muted">{view.appeals.length}</span>
          </div>
          {view.appeals.length === 0 ? (
            <p className="text-text-muted italic">No appeals recorded</p>
          ) : (
            <ul className="space-y-1">
              {view.appeals.map((appeal) => (
                <li key={appeal.node_id} className="flex items-start justify-between gap-3 rounded border border-border/80 bg-bg-elevated px-2 py-1.5">
                  <div>
                    <div className="break-all font-mono text-text-primary">{appeal.node_id}</div>
                    <div className="mt-1 text-text-muted">{appeal.state}</div>
                  </div>
                  <span className="shrink-0 rounded border border-border bg-bg-card px-1.5 py-0.5 text-[10px] text-text-muted">
                    {appeal.outcome ?? 'pending'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="font-medium text-text-primary">Review readiness</span>
            <span className={view.review.ready ? 'text-status-completed' : 'text-status-failed'}>
              {reviewLabel}
            </span>
          </div>
          {view.review.blockers.length === 0 ? (
            <p className="text-text-muted italic">No merge blockers</p>
          ) : (
            <ul className="space-y-1">
              {view.review.blockers.map((blocker) => (
                <li key={blocker} className="break-words rounded border border-border/80 bg-bg-elevated px-2 py-1 text-text-secondary">
                  {blocker}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
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

export function GraphPanel({ runId, run, open, onClose, activityEvents = [], initialNodeId = null }: GraphPanelProps) {
  const { data: projection } = useGraphProjection(runId);
  const { data: schedulerView } = useSchedulerView(runId);
  const { data: decisionView } = useDecisionView(runId);
  const { data: fileStateReport } = useFileStateReport(runId);
  const { data: events = [] } = useGraphEvents(runId);
  const [showEvents, setShowEvents] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (open && initialNodeId) {
      setSelectedNodeId(initialNodeId);
    }
  }, [initialNodeId, open]);

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
          <OperatorSummary
            projection={projection}
            schedulerView={schedulerView}
            decisionView={decisionView}
            activityEvents={activityEvents}
          />
          <GraphActivitySection activityEvents={activityEvents} />
          {schedulerView && <SchedulerView view={schedulerView} />}
          {decisionView && <DecisionsSection view={decisionView} />}
          {fileStateReport && <FileStateViewer report={fileStateReport} />}
          <NodeStatesTable
            projection={projection}
            events={events}
            activityEvents={activityEvents}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
          <NodeDetailPanel
            runId={runId}
            nodeId={selectedNodeId}
            onClose={() => setSelectedNodeId(null)}
          />
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
