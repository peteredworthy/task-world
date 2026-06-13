import type { SchedulerBlockedNode, SchedulerLease, SchedulerViewResponse } from '../types';

interface SchedulerViewProps {
  view: SchedulerViewResponse;
}

function DeferredList({
  title,
  nodes,
}: {
  title: string;
  nodes: SchedulerBlockedNode[];
}) {
  return (
    <div className="rounded border border-border bg-bg-card p-2">
      <h4 className="text-xs font-semibold text-text-primary">{title}</h4>
      {nodes.length === 0 ? (
        <p className="mt-2 text-xs text-text-muted italic">None</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {nodes.map((node) => (
            <li key={`${node.node_id}:${node.reason}`} className="text-xs">
              <div className="break-all font-mono text-text-primary">{node.node_id}</div>
              <div className="break-all text-[11px] text-text-muted">{node.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReadyList({ ready }: { ready: string[] }) {
  return (
    <div className="rounded border border-border bg-bg-card p-2">
      <h4 className="text-xs font-semibold text-text-primary">Ready</h4>
      {ready.length === 0 ? (
        <p className="mt-2 text-xs text-text-muted italic">None</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {ready.map((nodeId) => (
            <li key={nodeId} className="break-all font-mono text-xs text-text-primary">
              {nodeId}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LeasesTable({ leases }: { leases: SchedulerLease[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead className="text-text-muted">
          <tr>
            <th className="pr-3 pb-1">lease id</th>
            <th className="pr-3 pb-1">node</th>
            <th className="pr-3 pb-1">generation</th>
            <th className="pr-3 pb-1">state</th>
            <th className="pb-1">expiry</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {leases.length === 0 ? (
            <tr>
              <td colSpan={5} className="py-2 text-text-muted italic">
                No active or suspended leases
              </td>
            </tr>
          ) : (
            leases.map((lease) => (
              <tr key={lease.lease_id}>
                <td className="py-2 pr-3 break-all font-mono text-text-primary">{lease.lease_id}</td>
                <td className="py-2 pr-3 break-all font-mono text-text-secondary">{lease.node_id}</td>
                <td className="py-2 pr-3 text-text-secondary">{lease.generation ?? '-'}</td>
                <td className="py-2 pr-3 text-text-secondary">{lease.state}</td>
                <td className="py-2 text-text-secondary">{lease.expires_at ?? '-'}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function SchedulerView({ view }: SchedulerViewProps) {
  const leases = [...view.leases.active, ...view.leases.suspended];
  return (
    <section>
      <h3 className="text-sm font-semibold text-text-primary mb-2">Scheduler</h3>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ReadyList ready={view.scheduler.ready} />
        <DeferredList title="Blocked" nodes={view.scheduler.blocked} />
        <DeferredList title="Waiting resources" nodes={view.scheduler.waiting_resources} />
        <DeferredList title="Waiting gates" nodes={view.scheduler.waiting_gates} />
      </div>
      <h3 className="mt-4 text-sm font-semibold text-text-primary mb-2">Leases</h3>
      <LeasesTable leases={leases} />
    </section>
  );
}
