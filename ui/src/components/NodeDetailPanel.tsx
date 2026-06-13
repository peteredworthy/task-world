import { useGraphNodeDetail } from '../hooks/useApi';
import type { NodeDetailResponse } from '../types';

interface NodeDetailPanelProps {
  runId: string;
  nodeId: string | null;
  onClose: () => void;
}

function valueText(value: unknown): string {
  if (value == null || value === '') return '-';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

function recordTitle(record: Record<string, unknown>): string {
  return valueText(record.record_id ?? record.id ?? record.snapshot_id);
}

function leaseBadge(detail: NodeDetailResponse): string {
  const lease = detail.active_lease;
  if (!lease) return 'no lease';
  return `${valueText(lease.state)} ${valueText(lease.lease_id)}`;
}

function SummaryRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-start justify-between gap-3 text-xs">
      <dt className="text-text-muted">{label}</dt>
      <dd className="min-w-0 break-all font-mono text-text-secondary">{valueText(value)}</dd>
    </div>
  );
}

function InputsSection({ detail }: { detail: NodeDetailResponse }) {
  const entries = Object.entries(detail.input_ports);
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">Inputs</h3>
      {entries.length === 0 ? (
        <p className="text-xs italic text-text-muted">No bound input ports</p>
      ) : (
        <dl className="space-y-2">
          {entries.map(([port, recordIds]) => (
            <div key={port} className="rounded border border-border bg-bg-card px-2 py-2">
              <dt className="font-mono text-xs text-text-primary">{port}</dt>
              <dd className="mt-1 flex flex-wrap gap-1">
                {recordIds.length === 0 ? (
                  <span className="text-xs text-text-muted">-</span>
                ) : (
                  recordIds.map((recordId) => (
                    <span key={recordId} className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                      {recordId}
                    </span>
                  ))
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function RecordsSection({
  title,
  records,
  runId,
}: {
  title: string;
  records: Record<string, unknown>[];
  runId: string;
}) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">{title}</h3>
      {records.length === 0 ? (
        <p className="text-xs italic text-text-muted">No records</p>
      ) : (
        <ul className="space-y-2">
          {records.map((record, index) => (
            <li key={`${recordTitle(record)}-${index}`} className="rounded border border-border bg-bg-card p-2">
              <div className="flex items-center justify-between gap-3">
                <span className="break-all font-mono text-xs text-text-primary">{recordTitle(record)}</span>
                <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted">
                  {valueText(record.record_kind)}
                </span>
              </div>
              {'verdict' in record && (
                <p className="mt-1 text-xs text-text-secondary">verdict: {valueText(record.verdict)}</p>
              )}
              {'classification_summary' in record && (
                <pre className="mt-2 overflow-auto rounded bg-bg-muted p-2 text-[10px] text-text-secondary">
                  {JSON.stringify(record.classification_summary, null, 2)}
                </pre>
              )}
              {typeof record.patch_bundle_id === 'string' && record.patch_bundle_id.length > 0 && (
                <a
                  href={`/runs/${runId}/changes`}
                  className="mt-2 inline-flex text-xs text-accent-purple underline decoration-dotted hover:text-accent-purple/80"
                >
                  diff viewer: {record.patch_bundle_id}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CallbackHistorySection({ detail }: { detail: NodeDetailResponse }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text-primary">Callback history</h3>
      {detail.callback_history.length === 0 ? (
        <p className="text-xs italic text-text-muted">No callback events</p>
      ) : (
        <ol className="space-y-1">
          {detail.callback_history.map((event) => (
            <li key={event.event_id} className="rounded border border-border bg-bg-card px-2 py-1.5 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-text-primary">{event.event_type}</span>
                <time className="shrink-0 text-text-muted">{event.timestamp}</time>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function NodeDetailPanel({ runId, nodeId, onClose }: NodeDetailPanelProps) {
  const { data: detail, isLoading, error } = useGraphNodeDetail(runId, nodeId ?? undefined);

  if (!nodeId) return null;

  return (
    <div className="mt-4 rounded border border-border bg-bg-elevated p-3" data-testid="node-detail-panel">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary">Node detail</h3>
          <p className="mt-1 break-all font-mono text-xs text-text-muted">{nodeId}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-1 text-xs text-text-muted hover:bg-bg-hover hover:text-text-primary"
        >
          Close
        </button>
      </div>

      {isLoading && <p className="text-xs text-text-muted">Loading node facts...</p>}
      {error && <p className="text-xs text-status-failed">Unable to load node detail.</p>}

      {detail && (
        <div className="space-y-4">
          <dl className="space-y-1 rounded border border-border bg-bg-card p-2">
            <SummaryRow label="kind" value={detail.kind} />
            <SummaryRow label="role" value={detail.role} />
            <SummaryRow label="state" value={detail.state} />
            <SummaryRow label="lease" value={leaseBadge(detail)} />
          </dl>
          <InputsSection detail={detail} />
          <RecordsSection title="Outputs" records={detail.output_records} runId={runId} />
          <RecordsSection title="File-state" records={detail.file_state_records} runId={runId} />
          {detail.prompt_summary && <RecordsSection title="Prompt packet" records={[detail.prompt_summary]} runId={runId} />}
          <CallbackHistorySection detail={detail} />
        </div>
      )}
    </div>
  );
}
