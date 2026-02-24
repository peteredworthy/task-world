import { useConflicts } from '../../hooks/useReview';
import { ApiError } from '../../api/client';
import type { ConflictFile } from '../../types/review';

interface ConflictFileListProps {
  runId: string;
  onFileSelect?: (file: ConflictFile) => void;
}

function StatusChip({ status }: { status: ConflictFile['status'] }) {
  if (status === 'resolved') {
    return (
      <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-status-success/15 text-status-success">
        Resolved
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-status-failed/15 text-status-failed">
      Unresolved
    </span>
  );
}

function ConflictFileRow({
  file,
  onClick,
}: {
  file: ConflictFile;
  onClick?: (file: ConflictFile) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick?.(file)}
      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-bg-muted transition-colors group"
    >
      {/* Conflict icon */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 text-amber-400"
        aria-hidden="true"
      >
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>

      <span className="flex-1 truncate font-mono text-xs text-text-secondary group-hover:text-text-primary">
        {file.path}
      </span>

      <span className="shrink-0 text-[10px] text-text-muted">{file.block_count}×</span>

      <StatusChip status={file.status} />
    </button>
  );
}

export function ConflictFileList({ runId, onFileSelect }: ConflictFileListProps) {
  const { data, isLoading, isError, error, refetch } = useConflicts(runId);

  if (isLoading) {
    return (
      <div className="rounded-md border border-border bg-bg-elevated p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
          Conflicts
        </h3>
        <p className="mt-2 text-xs text-text-muted">Loading conflicts…</p>
      </div>
    );
  }

  if (isError) {
    const message =
      error instanceof ApiError ? error.message : 'Failed to load conflicts.';
    return (
      <div className="rounded-md border border-status-failed/30 bg-status-failed/10 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
          Conflicts
        </h3>
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

  // Hidden when no conflicts (data not yet loaded or truly empty)
  if (!data || data.length === 0) {
    return null;
  }

  // All conflicts resolved — show a clean state instead of hiding
  const unresolvedCount = data.filter((f) => f.status === 'unresolved').length;
  if (unresolvedCount === 0) {
    return (
      <div className="rounded-md border border-status-success/30 bg-status-success/5 p-4">
        <div className="flex items-center gap-2">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 text-status-success"
            aria-hidden="true"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
            Conflicts
          </h3>
          <span className="text-xs text-status-success">All resolved</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
        Conflicts
        <span className="ml-1.5 font-normal text-text-muted">({data.length})</span>
        {unresolvedCount > 0 && (
          <span className="ml-1.5 font-normal text-status-failed">
            · {unresolvedCount} unresolved
          </span>
        )}
      </h3>

      <div className="mt-2 flex flex-col gap-0.5">
        {data.map((file) => (
          <ConflictFileRow
            key={file.path}
            file={file}
            onClick={onFileSelect}
          />
        ))}
      </div>
    </div>
  );
}
