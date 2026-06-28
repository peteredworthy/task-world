import { Spinner } from '../Spinner';
import { formatDuration, formatTokens } from '../../lib/format';
import { ApiError } from '../../api/client';
import { useRunEvidenceDigest } from '../../hooks/useApi';
import type { RunEvidenceDigestResponse } from '../../types';

function formatCost(value: number | null): string {
  if (value === null) return '—';
  if (value === 0) return '$0.00';
  if (value < 0.001) return '<$0.001';
  if (value < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-bg-elevated/50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="mt-1 text-sm font-medium text-text-primary">{value}</div>
    </div>
  );
}

function NodeRow({ node }: { node: RunEvidenceDigestResponse['representative_nodes'][number] }) {
  return (
    <li className="rounded border border-border bg-bg-elevated/50 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-mono text-sm text-text-primary">{node.node_id}</div>
          <div className="mt-1 text-xs text-text-secondary">
            {node.title ?? 'Untitled'}
            {node.role ? ` · ${node.role}` : ''}
            {node.state ? ` · ${node.state}` : ''}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 text-[11px] text-text-muted">
          {node.blockers.length > 0 && (
            <span className="rounded border border-status-failed/35 bg-status-failed/10 px-1.5 py-0.5 text-status-failed">
              {node.blockers.length} blocker{node.blockers.length === 1 ? '' : 's'}
            </span>
          )}
          {node.evidence_summary === null && (
            <span className="rounded border border-border bg-bg-card px-1.5 py-0.5">
              evidence hidden
            </span>
          )}
        </div>
      </div>
      {node.evidence_summary && (
        <p className="mt-2 text-xs text-text-muted">{node.evidence_summary}</p>
      )}
      {node.blockers.length > 0 && (
        <p className="mt-2 text-xs text-text-secondary">{node.blockers.join(' · ')}</p>
      )}
    </li>
  );
}

interface RunEvidenceDigestProps {
  runId: string | undefined;
  enabled?: boolean;
}

export function RunEvidenceDigest({ runId, enabled = true }: RunEvidenceDigestProps) {
  const { data, isLoading, error } = useRunEvidenceDigest(runId, {
    enabled,
    include_node_evidence: false,
  });

  if (!enabled || !runId) {
    return null;
  }

  if (isLoading) {
    return (
      <section className="mb-6 rounded-lg border border-border bg-bg-card p-4">
        <div className="flex items-center gap-2 text-sm text-text-secondary">
          <Spinner />
          <span>Loading Run Evidence Digest…</span>
        </div>
      </section>
    );
  }

  if (error) {
    const message = error instanceof ApiError ? error.message : 'Failed to load run evidence digest.';
    return (
      <section className="mb-6 rounded-lg border border-status-failed/30 bg-status-failed/5 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
          Run Evidence Digest
        </h2>
        <p className="mt-2 text-sm text-status-failed">{message}</p>
      </section>
    );
  }

  if (!data) {
    return null;
  }

  const graphLabel = data.is_graph_backed ? 'Graph-backed' : 'Legacy';
  const blockerPreview = data.blockers.slice(0, 4);
  const hiddenEvidence = data.representative_nodes.some((node) => node.evidence_summary === null);

  return (
    <section className="mb-6 rounded-lg border border-border bg-bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-text-primary">
            Run Evidence Digest
          </h2>
          <p className="mt-1 text-xs text-text-secondary">
            Compact readback of run status, blockers, scheduler state, and cost/runtime metrics.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded border border-border bg-bg-elevated px-2 py-1 text-text-muted">
            {data.status}
          </span>
          <span className="rounded border border-border bg-bg-elevated px-2 py-1 text-text-muted">
            {graphLabel}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Blockers" value={data.blockers.length.toString()} />
        <Stat label="Scheduler" value={`${data.scheduler.blocked_count} blocked / ${data.scheduler.ready_count} ready`} />
        <Stat label="Nodes" value={data.representative_nodes.length.toString()} />
        <Stat label="Runtime" value={formatDuration(data.metrics.total_duration_ms)} />
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Tokens read" value={formatTokens(data.metrics.total_tokens_read)} />
        <Stat label="Tokens write" value={formatTokens(data.metrics.total_tokens_write)} />
        <Stat label="Tokens cache" value={formatTokens(data.metrics.total_tokens_cache)} />
        <Stat label="Cost" value={formatCost(data.metrics.estimated_cost_usd)} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Blockers
          </div>
          {data.blockers.length === 0 ? (
            <p className="text-sm text-text-muted italic">No blockers reported.</p>
          ) : (
            <ul className="space-y-1">
              {blockerPreview.map((blocker) => (
                <li key={blocker} className="rounded border border-border bg-bg-elevated/50 px-3 py-2 text-xs text-text-secondary">
                  {blocker}
                </li>
              ))}
              {data.blockers.length > blockerPreview.length && (
                <li className="px-3 py-1 text-xs text-text-muted">
                  and {data.blockers.length - blockerPreview.length} more
                </li>
              )}
            </ul>
          )}
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Representative nodes
            </div>
            <div className="text-xs text-text-muted">
              {data.scheduler.graph_event_count} graph events
            </div>
          </div>
          {data.representative_nodes.length === 0 ? (
            <p className="text-sm text-text-muted italic">
              {data.is_graph_backed ? 'No representative nodes available yet.' : 'Legacy run has no graph evidence.'}
            </p>
          ) : (
            <>
              {hiddenEvidence && (
                <p className="mb-2 text-xs text-text-muted">
                  Raw node evidence is hidden in this digest view.
                </p>
              )}
              <ul className="space-y-2">
                {data.representative_nodes.map((node) => (
                  <NodeRow key={node.node_id} node={node} />
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
