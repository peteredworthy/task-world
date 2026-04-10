import { useState } from 'react';
import { ApiError } from '../../api/client';
import { useBranchStatus } from '../../hooks/useReview';

interface BranchStatusSectionProps {
  runId: string;
  worktreePath: string | null;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      title="Copy to clipboard"
      className="ml-1.5 rounded px-1.5 py-0.5 text-xs text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors"
    >
      {copied ? '✓' : 'Copy'}
    </button>
  );
}

function MetaRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-text-muted">{label}</span>
      <span className={mono ? 'font-mono text-xs text-text-secondary break-all' : 'text-xs text-text-secondary'}>
        {value}
      </span>
    </div>
  );
}

export function BranchStatusSection({ runId, worktreePath }: BranchStatusSectionProps) {
  const { data, isLoading, isError, error, refetch } = useBranchStatus(runId);

  if (isLoading) {
    return (
      <div className="rounded-md border border-border bg-bg-elevated p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">Branch Status</h3>
        <p className="mt-2 text-xs text-text-muted">Loading branch status…</p>
      </div>
    );
  }

  if (isError || !data) {
    const message = error instanceof ApiError ? error.message : 'Failed to load branch status.';
    return (
      <div className="rounded-md border border-status-failed/30 bg-status-failed/10 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">Branch Status</h3>
        <p className="mt-2 text-xs text-status-failed">{message}</p>
        <button
          onClick={() => void refetch()}
          className="mt-2 rounded border border-status-failed/40 px-2 py-1 text-xs text-status-failed hover:bg-status-failed/10"
        >
          Retry
        </button>
      </div>
    );
  }

  const dataExtra = data as unknown as Record<string, unknown>;
  const baseSha = typeof dataExtra.base_sha === 'string' ? dataExtra.base_sha : undefined;
  const headSha = typeof dataExtra.head_sha === 'string' ? dataExtra.head_sha : undefined;

  return (
    <div className="rounded-md border border-border bg-bg-elevated p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">Branch Status</h3>

      <div className="mt-3 grid grid-cols-1 gap-3">
        <MetaRow label="Branch" value={data.run_branch} mono />
        <MetaRow label="Target Branch" value={data.source_branch} mono />

        {baseSha && <MetaRow label="Base SHA" value={baseSha} mono />}
        {headSha && <MetaRow label="Head SHA" value={headSha} mono />}

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-md border border-border bg-bg-muted px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-text-muted">Behind</p>
            <p className="mt-0.5 text-lg font-semibold text-text-primary">{data.behind_count}</p>
          </div>
          <div className="rounded-md border border-border bg-bg-muted px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-text-muted">Ahead</p>
            <p className="mt-0.5 text-lg font-semibold text-text-primary">{data.ahead_count}</p>
          </div>
        </div>

        {worktreePath && (
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wide text-text-muted">Worktree Path</span>
            <div className="flex items-center gap-1">
              <span className="font-mono text-xs text-text-secondary break-all">{worktreePath}</span>
              <CopyButton text={worktreePath} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
