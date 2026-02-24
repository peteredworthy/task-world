import { useState, useEffect, useRef } from 'react';
import { ApiError } from '../../api/client';
import { useDiffFiles } from '../../hooks/useReview';
import type { DiffFileEntry } from '../../types/review';

interface FileListSectionProps {
  runId: string;
  onFileSelect?: (file: DiffFileEntry) => void;
  onPruneFile?: (file: DiffFileEntry) => void;
}

function StatusIcon({ status }: { status: DiffFileEntry['status'] }) {
  switch (status) {
    case 'added':
      return (
        <span
          title="Added"
          className="inline-flex h-4 w-4 items-center justify-center rounded text-[10px] font-bold text-status-success bg-status-success/15"
        >
          A
        </span>
      );
    case 'deleted':
      return (
        <span
          title="Deleted"
          className="inline-flex h-4 w-4 items-center justify-center rounded text-[10px] font-bold text-status-failed bg-status-failed/15"
        >
          D
        </span>
      );
    case 'renamed':
      return (
        <span
          title="Renamed"
          className="inline-flex h-4 w-4 items-center justify-center rounded text-[10px] font-bold text-status-running bg-status-running/15"
        >
          R
        </span>
      );
    default:
      return (
        <span
          title="Modified"
          className="inline-flex h-4 w-4 items-center justify-center rounded text-[10px] font-bold text-status-pending bg-status-pending/15"
        >
          M
        </span>
      );
  }
}

function FileRow({
  file,
  onClick,
  onPruneFile,
}: {
  file: DiffFileEntry;
  onClick?: (file: DiffFileEntry) => void;
  onPruneFile?: (file: DiffFileEntry) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  return (
    <div className="relative flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-bg-muted transition-colors group">
      <button
        type="button"
        onClick={() => onClick?.(file)}
        className="flex flex-1 items-center gap-2 min-w-0"
      >
        <StatusIcon status={file.status} />
        <span className="flex-1 truncate font-mono text-xs text-text-secondary group-hover:text-text-primary">
          {file.path}
        </span>
      </button>
      <span className="shrink-0 text-xs text-status-success">+{file.additions}</span>
      <span className="shrink-0 text-xs text-status-failed">-{file.deletions}</span>

      {/* Three-dot context menu */}
      {onPruneFile && (
        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((prev) => !prev);
            }}
            className="rounded p-0.5 text-text-muted hover:text-text-primary opacity-0 group-hover:opacity-100 transition-opacity"
            title="File actions"
            aria-label="File actions menu"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
              <circle cx="8" cy="3" r="1.5" />
              <circle cx="8" cy="8" r="1.5" />
              <circle cx="8" cy="13" r="1.5" />
            </svg>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full z-20 mt-1 min-w-[120px] rounded border border-border bg-bg-elevated shadow-lg">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onPruneFile(file);
                  setMenuOpen(false);
                }}
                className="block w-full px-3 py-1.5 text-left text-xs text-text-secondary hover:bg-bg-muted hover:text-text-primary transition-colors"
              >
                Prune File
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function FileListSection({ runId, onFileSelect, onPruneFile }: FileListSectionProps) {
  const { data, isLoading, isError, error, refetch } = useDiffFiles(runId);

  if (isLoading) {
    return (
      <div className="rounded-md border border-border bg-bg-elevated p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
          Modified Files
        </h3>
        <div className="mt-2 flex flex-col gap-1.5" aria-label="Loading file list">
          {[40, 65, 55, 48, 70].map((w, i) => (
            <div key={i} className="flex items-center gap-2 px-2 py-1.5">
              <span className="skeleton h-4 w-4 shrink-0" />
              <span className="skeleton h-3 flex-1" style={{ maxWidth: `${w}%` }} />
              <span className="skeleton h-3 w-6 shrink-0" />
              <span className="skeleton h-3 w-6 shrink-0" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (isError || !data) {
    const message =
      error instanceof ApiError ? error.message : 'Failed to load file list.';
    return (
      <div className="rounded-md border border-status-failed/30 bg-status-failed/10 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
          Modified Files
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

  return (
    <div className="rounded-md border border-border bg-bg-elevated p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
        Modified Files
        {data.length > 0 && (
          <span className="ml-1.5 font-normal text-text-muted">({data.length})</span>
        )}
      </h3>

      {data.length === 0 ? (
        <div className="mt-4 flex flex-col items-center gap-2 py-4 text-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-text-muted opacity-50"
            aria-hidden="true"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
          <p className="text-xs text-text-muted">Nothing to review</p>
        </div>
      ) : (
        <div className="mt-2 flex flex-col gap-0.5">
          {data.map((file) => (
            <FileRow
              key={file.path}
              file={file}
              onClick={onFileSelect}
              onPruneFile={onPruneFile}
            />
          ))}
        </div>
      )}
    </div>
  );
}
