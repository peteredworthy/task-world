import type { FileStateBoundary, FileStatePath, FileStateReportResponse } from '../types';

function formatCount([classification, count]: [string, number]) {
  return `${classification}: ${count}`;
}

function PathList({ title, paths }: { title: string; paths: FileStatePath[] }) {
  if (paths.length === 0) {
    return null;
  }

  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold text-text-secondary">{title}</h4>
      <ul className="space-y-1">
        {paths.map((path) => (
          <li key={`${title}-${path.path}`} className="rounded border border-border bg-bg-muted px-2 py-1 text-xs">
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0 break-all font-mono text-text-primary">{path.path}</span>
              <span className="shrink-0 text-text-muted">{path.classification ?? 'unknown'}</span>
            </div>
            {(path.reason || path.matched_rule) && (
              <p className="mt-1 text-[11px] text-text-muted">
                {path.reason ?? path.matched_rule}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PathTruncationNotice({
  sourceEntriesTotal,
  shown,
  truncated,
}: {
  sourceEntriesTotal: number;
  shown: number;
  truncated: boolean;
}) {
  if (!truncated) return null;
  return (
    <p className="mt-1 text-[11px] text-text-muted">
      Showing first {shown} paths from {sourceEntriesTotal} source entries; additional unique paths omitted.
    </p>
  );
}

function VerdictTruncationNotice({
  total,
  shown,
  truncated,
}: {
  total: number | null;
  shown: number;
  truncated: boolean;
}) {
  if (!truncated) return null;
  if (total === null) {
    return <p className="mt-1 text-[11px] text-text-muted">Showing {shown} verdicts; additional verdict facts were capped.</p>;
  }
  return <p className="mt-1 text-[11px] text-text-muted">Showing first {shown} of {total} verdict entries; additional verdict entries omitted.</p>;
}

function GatekeeperAggregateSummary({ report }: { report: FileStateReportResponse }) {
  if (report.gatekeeper === null) return null;
  const partial = report.has_more || report.gatekeeper_metrics_truncated;
  const prefix = partial ? 'Partial — at least' : 'Total';
  const consults = Number(report.gatekeeper.gatekeeper_consults ?? 0);
  const tokens = Number(report.gatekeeper.gen_ai_usage_input_tokens ?? 0);
  const cost = Number(report.gatekeeper.cost_usd ?? 0);
  const models = report.gatekeeper.models as Record<string, Record<string, unknown>> | undefined;
  return (
    <div className="mt-3 rounded border border-border bg-bg-muted p-2 text-xs text-text-secondary" aria-live="polite">
      <p>{prefix} gatekeeper aggregates: {consults} consults, {tokens} input tokens, ${cost.toFixed(4)} cost.</p>
      {partial && (
        <p className="mt-1">
          {report.has_more
            ? 'Additional boundary pages have not been loaded; aggregate and model totals are partial.'
            : 'Additional gatekeeper facts were capped; aggregate and model totals are partial.'}
        </p>
      )}
      {Object.entries(models ?? {}).map(([modelId, model]) => (
        <p key={modelId} className="mt-1">
          {modelId}: {partial ? 'partial — at least' : 'total'} {Number(model.gen_ai_usage_input_tokens ?? 0)} input tokens, ${Number(model.cost_usd ?? 0).toFixed(4)}.
        </p>
      ))}
    </div>
  );
}

function DiffSummary({ boundary }: { boundary: FileStateBoundary }) {
  if (!boundary.diff_summary_available || !boundary.diff_summary) {
    return <p className="text-xs text-text-muted">Diff summary unavailable</p>;
  }
  if (boundary.snapshot_type !== 'git_commit') {
    return null;
  }

  const additions = boundary.diff_summary.additions;
  const deletions = boundary.diff_summary.deletions;
  const lineCounts = additions !== null && deletions !== null
    ? ` / +${additions} -${deletions}`
    : '';

  return (
    <p className="text-xs text-accent-purple">
      diff summary: {boundary.diff_summary.files_changed} files changed{lineCounts}
    </p>
  );
}

function BoundaryCard({ boundary }: { boundary: FileStateBoundary }) {
  const counts = Object.entries(boundary.classification_counts).sort(([left], [right]) => left.localeCompare(right));

  return (
    <li className="rounded border border-border bg-bg-card p-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-all font-mono text-xs text-text-primary">{boundary.snapshot_id}</p>
          <p className="mt-1 text-[11px] text-text-muted">
            {boundary.snapshot_type} / {boundary.record_id}
          </p>
        </div>
        <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted">
          {boundary.verdict ?? 'unknown'}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {counts.length === 0 ? (
          <span className="text-xs text-text-muted">No classifications</span>
        ) : (
          counts.map((entry) => (
            <span key={entry[0]} className="rounded bg-bg-muted px-1.5 py-0.5 text-[10px] text-text-secondary">
              {formatCount(entry)}
            </span>
          ))
        )}
      </div>
      <div className="mt-2">
        <DiffSummary boundary={boundary} />
      </div>
      <div className="mt-3 space-y-3">
        <PathList title="Captured paths" paths={boundary.captured_paths} />
        <PathTruncationNotice
          sourceEntriesTotal={boundary.captured_source_entries_total}
          shown={boundary.captured_paths.length}
          truncated={boundary.captured_paths_truncated}
        />
        <PathList title="Rejected paths" paths={boundary.rejected_paths} />
        <PathTruncationNotice
          sourceEntriesTotal={boundary.rejected_source_entries_total}
          shown={boundary.rejected_paths.length}
          truncated={boundary.rejected_paths_truncated}
        />
        {boundary.gatekeeper_verdicts.length > 0 && (
          <div>
            <h4 className="mb-1 text-xs font-semibold text-text-secondary">Gatekeeper verdicts</h4>
            <ul className="space-y-1">
              {boundary.gatekeeper_verdicts.map((verdict) => (
                <li key={verdict.path} className="rounded border border-border bg-bg-muted px-2 py-1 text-xs">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0 break-all font-mono text-text-primary">{verdict.path}</span>
                    <span className="shrink-0 text-text-muted">
                      {verdict.verdict} / {verdict.classification ?? 'unknown'}
                    </span>
                  </div>
                  {verdict.rationale && (
                    <p className="mt-1 text-[11px] text-text-muted">{verdict.rationale}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        <VerdictTruncationNotice
          total={boundary.gatekeeper_verdicts_total}
          shown={boundary.gatekeeper_verdicts.length}
          truncated={boundary.gatekeeper_verdicts_truncated}
        />
      </div>
    </li>
  );
}

export function FileStateViewer({
  report,
  onLoadMore,
  isLoadingMore = false,
}: {
  report: FileStateReportResponse;
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
}) {
  return (
    <section data-testid="file-state-viewer">
      <h3 className="mb-2 text-sm font-semibold text-text-primary">File-state</h3>
      {report.nodes.length === 0 ? (
        <p className="text-xs italic text-text-muted">No file-state records</p>
      ) : (
        <div className="space-y-3">
          {report.nodes.map((node) => (
            <div key={node.node_id}>
              <h4 className="mb-1 break-all font-mono text-xs text-text-secondary">{node.node_id}</h4>
              <ul className="space-y-2">
                {node.boundaries.map((boundary) => (
                  <BoundaryCard key={boundary.record_id} boundary={boundary} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {report.has_more && onLoadMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={isLoadingMore}
          className="mt-3 text-xs text-accent-purple underline decoration-dotted disabled:cursor-wait disabled:opacity-60"
        >
          {isLoadingMore ? 'Loading file-state records…' : 'Load more file-state records'}
        </button>
      )}
      <GatekeeperAggregateSummary report={report} />
    </section>
  );
}
