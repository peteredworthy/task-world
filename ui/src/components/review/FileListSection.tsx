import { useState, useEffect, useRef, useMemo } from 'react';
import { ApiError } from '../../api/client';
import { useDiffFiles } from '../../hooks/useReview';
import type { DiffFileEntry } from '../../types/review';

interface FileListSectionProps {
  runId: string;
  selectedFilePath?: string | null;
  onFileSelect?: (file: DiffFileEntry) => void;
  onPruneFile?: (file: DiffFileEntry) => void;
}

// ── Tree types ────────────────────────────────────────────────────────────────

interface DirNode {
  type: 'dir';
  name: string;
  /** Full path from root, e.g. "src/components" */
  path: string;
  children: TreeNode[];
}

interface FileLeaf {
  type: 'file';
  /** Basename only, e.g. "DiffViewer.tsx" */
  name: string;
  entry: DiffFileEntry;
}

type TreeNode = DirNode | FileLeaf;

function buildFileTree(files: DiffFileEntry[]): TreeNode[] {
  const root: TreeNode[] = [];
  for (const file of files) {
    const parts = file.path.split('/');
    let current = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      let dir = current.find((n) => n.type === 'dir' && n.name === part) as DirNode | undefined;
      if (!dir) {
        dir = {
          type: 'dir',
          name: part,
          path: parts.slice(0, i + 1).join('/'),
          children: [],
        };
        current.push(dir);
      }
      current = dir.children;
    }
    current.push({ type: 'file', name: parts[parts.length - 1], entry: file });
  }
  return root;
}

function collectDirPaths(nodes: TreeNode[]): string[] {
  const paths: string[] = [];
  for (const n of nodes) {
    if (n.type === 'dir') {
      paths.push(n.path);
      paths.push(...collectDirPaths(n.children));
    }
  }
  return paths;
}

// ── Status icon ───────────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: DiffFileEntry['status'] }) {
  switch (status) {
    case 'added':
      return (
        <span
          title="Added"
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold text-status-success bg-status-success/15"
        >
          A
        </span>
      );
    case 'deleted':
      return (
        <span
          title="Deleted"
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold text-status-failed bg-status-failed/15"
        >
          D
        </span>
      );
    case 'renamed':
      return (
        <span
          title="Renamed"
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold text-status-running bg-status-running/15"
        >
          R
        </span>
      );
    default:
      return (
        <span
          title="Modified"
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold text-status-pending bg-status-pending/15"
        >
          M
        </span>
      );
  }
}

// ── File row ──────────────────────────────────────────────────────────────────

function FileRow({
  file,
  isSelected,
  onClick,
  onPruneFile,
  depth = 0,
  displayName,
}: {
  file: DiffFileEntry;
  isSelected?: boolean;
  onClick?: (file: DiffFileEntry) => void;
  onPruneFile?: (file: DiffFileEntry) => void;
  depth?: number;
  displayName?: string;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
    <div
      className={`relative flex w-full items-center gap-2 rounded pr-2 py-1.5 text-left transition-colors group ${
        isSelected ? 'bg-blue-500/12 ring-1 ring-blue-500/25' : 'hover:bg-bg-muted'
      }`}
      style={{ paddingLeft: `${depth * 14 + 8}px` }}
    >
      <button
        type="button"
        onClick={() => onClick?.(file)}
        aria-pressed={isSelected}
        className="flex flex-1 items-center gap-2 min-w-0"
      >
        <StatusIcon status={file.status} />
        <span
          className={`flex-1 truncate font-mono text-xs ${
            isSelected ? 'text-text-primary' : 'text-text-secondary group-hover:text-text-primary'
          }`}
          title={file.path}
        >
          {displayName ?? file.path}
        </span>
      </button>
      <span className="shrink-0 text-xs text-status-success">+{file.additions}</span>
      <span className="shrink-0 text-xs text-status-failed">-{file.deletions}</span>

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

// ── Directory row ─────────────────────────────────────────────────────────────

function DirRow({
  name,
  depth,
  isOpen,
  onToggle,
}: {
  name: string;
  depth: number;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-1.5 rounded py-1 text-left hover:bg-bg-muted transition-colors"
      style={{ paddingLeft: `${depth * 14 + 8}px` }}
    >
      <svg
        className={`shrink-0 text-text-muted transition-transform duration-150 ${isOpen ? '' : '-rotate-90'}`}
        width="10"
        height="10"
        viewBox="0 0 10 10"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M5 7L1 3h8L5 7z" />
      </svg>
      <svg
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 text-text-muted"
        aria-hidden="true"
      >
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      </svg>
      <span className="text-xs text-text-muted font-medium">{name}/</span>
    </button>
  );
}

// ── Recursive tree node ───────────────────────────────────────────────────────

function FileTreeNode({
  node,
  depth,
  selectedFilePath,
  onFileSelect,
  onPruneFile,
  openDirs,
  onToggleDir,
}: {
  node: TreeNode;
  depth: number;
  selectedFilePath?: string | null;
  onFileSelect?: (file: DiffFileEntry) => void;
  onPruneFile?: (file: DiffFileEntry) => void;
  openDirs: Set<string>;
  onToggleDir: (path: string) => void;
}) {
  if (node.type === 'file') {
    return (
      <FileRow
        file={node.entry}
        isSelected={selectedFilePath === node.entry.path}
        onClick={onFileSelect}
        onPruneFile={onPruneFile}
        depth={depth}
        displayName={node.name}
      />
    );
  }

  const isOpen = openDirs.has(node.path);
  return (
    <div>
      <DirRow
        name={node.name}
        depth={depth}
        isOpen={isOpen}
        onToggle={() => onToggleDir(node.path)}
      />
      {isOpen &&
        node.children.map((child) => (
          <FileTreeNode
            key={child.type === 'dir' ? child.path : child.entry.path}
            node={child}
            depth={depth + 1}
            selectedFilePath={selectedFilePath}
            onFileSelect={onFileSelect}
            onPruneFile={onPruneFile}
            openDirs={openDirs}
            onToggleDir={onToggleDir}
          />
        ))}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function FileListSection({ runId, selectedFilePath, onFileSelect, onPruneFile }: FileListSectionProps) {
  const { data, isLoading, isError, error, refetch } = useDiffFiles(runId);

  const tree = useMemo(() => buildFileTree(data ?? []), [data]);

  const [openDirs, setOpenDirs] = useState<Set<string>>(new Set());

  // Initialise all directories as expanded whenever the file list changes
  useEffect(() => {
    setOpenDirs(new Set(collectDirPaths(tree)));
  }, [tree]);

  const toggleDir = (path: string) => {
    setOpenDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

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
        <div className="mt-2 flex flex-col gap-0">
          {tree.map((node) => (
            <FileTreeNode
              key={node.type === 'dir' ? node.path : node.entry.path}
              node={node}
              depth={0}
              selectedFilePath={selectedFilePath}
              onFileSelect={onFileSelect}
              onPruneFile={onPruneFile}
              openDirs={openDirs}
              onToggleDir={toggleDir}
            />
          ))}
        </div>
      )}
    </div>
  );
}
