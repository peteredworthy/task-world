import { useState, useEffect, useMemo, useRef } from 'react';
import { parseDiff, Diff, Hunk } from 'react-diff-view';
import type { ViewType, HunkData } from 'react-diff-view';
import 'react-diff-view/style/index.css';
import { usePruneGutter } from './PruneGutter';

/** Files with more changed lines than this threshold are collapsed by default. */
const LARGE_DIFF_THRESHOLD = 1000;

/** Count total changed lines in a file's hunks. */
function countFileLines(hunks: HunkData[]): number {
  return hunks.reduce((sum, h) => sum + h.changes.length, 0);
}

/** Detect binary file entries in raw git diff text, returns a set of file paths. */
function detectBinaryFiles(diffText: string): Set<string> {
  const binaryPaths = new Set<string>();
  // Patterns: "Binary files a/path and b/path differ"
  //           "Binary files /dev/null and b/path differ"
  //           "GIT binary patch"
  const lines = diffText.split('\n');
  let currentPath: string | null = null;
  for (const line of lines) {
    // Track current file from diff header
    if (line.startsWith('diff --git ')) {
      // Extract the b/ path: "diff --git a/foo b/foo" → foo
      const match = /^diff --git a\/.+ b\/(.+)$/.exec(line);
      if (match) {
        currentPath = match[1];
      }
    } else if (line.startsWith('Binary files ') || line.startsWith('GIT binary patch')) {
      if (currentPath) {
        binaryPaths.add(currentPath);
      }
    }
  }
  return binaryPaths;
}

/** Display a binary file placeholder instead of an inline diff. */
function BinaryFileView({ filePath }: { filePath: string }) {
  const ext = filePath.includes('.') ? filePath.split('.').pop()?.toUpperCase() ?? '' : '';
  return (
    <div className="mb-4">
      <div className="rounded-t border border-border bg-bg-muted px-3 py-1.5">
        <span className="font-mono text-xs text-text-secondary">{filePath}</span>
      </div>
      <div className="flex items-center gap-3 rounded-b border border-t-0 border-border bg-bg-elevated px-4 py-5">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="shrink-0 text-text-muted opacity-60"
          aria-hidden="true"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <div>
          <p className="text-sm font-medium text-text-secondary">Binary file</p>
          <p className="text-xs text-text-muted mt-0.5">
            Line-level diff not available
            {ext ? ` · ${ext} file` : ''}
          </p>
        </div>
      </div>
    </div>
  );
}

export interface DiffViewerProps {
  diffText: string;
  viewType?: ViewType;
  /** Increment to expand all file sections. */
  expandAllSignal?: number;
  /** Increment to collapse all file sections. */
  collapseAllSignal?: number;
}

interface DiffFileItemProps {
  oldRevision: string | undefined;
  newRevision: string | undefined;
  newPath: string | undefined;
  oldPath: string | undefined;
  type: Parameters<typeof Diff>[0]['diffType'];
  hunks: HunkData[];
  viewType: ViewType;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

/**
 * Renders a single file's diff with prune gutter support.
 * Extracted as a component so usePruneGutter (a hook) can be called per-file.
 */
function DiffFileItem({
  oldRevision,
  newRevision,
  newPath,
  oldPath,
  type,
  hunks,
  viewType,
  collapsed,
  onToggleCollapse,
}: DiffFileItemProps) {
  const filePath = newPath ?? oldPath ?? '';
  const renderGutter = usePruneGutter({ filePath, hunks });
  const lineCount = countFileLines(hunks);

  return (
    <div key={`${oldRevision ?? ''}-${newRevision ?? ''}-${newPath}`} className="mb-4">
      <div className="rounded-t border border-border bg-bg-muted px-3 py-1.5 flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
          aria-label={collapsed ? 'Expand file diff' : 'Collapse file diff'}
          aria-expanded={!collapsed}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            fill="currentColor"
            aria-hidden="true"
            className={`transition-transform duration-150 ${collapsed ? '-rotate-90' : ''}`}
          >
            <path d="M6 8L2 4h8L6 8z" />
          </svg>
        </button>
        <span className="flex-1 font-mono text-xs text-text-secondary">
          {newPath ?? oldPath ?? 'unknown'}
        </span>
        {collapsed && lineCount > 0 && (
          <span className="text-xs text-text-muted tabular-nums">
            {lineCount.toLocaleString()} lines
          </span>
        )}
      </div>
      {!collapsed && (
        <div className="overflow-auto rounded-b border border-t-0 border-border text-xs">
          <Diff
            viewType={viewType}
            diffType={type}
            hunks={hunks}
            renderGutter={renderGutter}
          >
            {(h) => h.map((hunk) => (
              <Hunk key={hunk.content} hunk={hunk} />
            ))}
          </Diff>
        </div>
      )}
    </div>
  );
}

export function DiffViewer({ diffText, viewType = 'unified', expandAllSignal, collapseAllSignal }: DiffViewerProps) {
  const { files, parseError, binaryFiles } = useMemo(() => {
    if (!diffText || diffText.trim() === '') {
      return { files: [], parseError: null, binaryFiles: new Set<string>() };
    }
    const binaryFiles = detectBinaryFiles(diffText);
    try {
      const parsed = parseDiff(diffText);
      return { files: parsed, parseError: null, binaryFiles };
    } catch (err) {
      return { files: [], parseError: err instanceof Error ? err.message : 'Failed to parse diff', binaryFiles };
    }
  }, [diffText]);

  const [collapsedFiles, setCollapsedFiles] = useState<Set<string>>(new Set());

  // When diffText changes, reset collapsed state — auto-collapse large files
  useEffect(() => {
    if (!diffText || diffText.trim() === '') {
      setCollapsedFiles(new Set());
      return;
    }
    try {
      const parsed = parseDiff(diffText);
      const initial = new Set<string>();
      for (const file of parsed) {
        const lines = file.hunks.reduce((sum, h) => sum + h.changes.length, 0);
        if (lines > LARGE_DIFF_THRESHOLD) {
          initial.add(file.newPath ?? file.oldPath ?? '');
        }
      }
      setCollapsedFiles(initial);
    } catch {
      setCollapsedFiles(new Set());
    }
  }, [diffText]);

  // Respond to expandAll signal — only when signal value changes
  const prevExpandRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (expandAllSignal !== undefined && expandAllSignal !== prevExpandRef.current) {
      prevExpandRef.current = expandAllSignal;
      setCollapsedFiles(new Set());
    }
  }, [expandAllSignal]);

  // Respond to collapseAll signal — only when signal value changes
  const prevCollapseRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (collapseAllSignal !== undefined && collapseAllSignal !== prevCollapseRef.current) {
      prevCollapseRef.current = collapseAllSignal;
      setCollapsedFiles(
        new Set(files.map((f) => f.newPath ?? f.oldPath ?? '').filter(Boolean)),
      );
    }
  }, [collapseAllSignal, files]);

  const toggleCollapse = (fileKey: string) => {
    setCollapsedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(fileKey)) {
        next.delete(fileKey);
      } else {
        next.add(fileKey);
      }
      return next;
    });
  };

  if (!diffText || diffText.trim() === '') {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-text-muted">
        No changes in this scope.
      </div>
    );
  }

  if (parseError) {
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-xs text-status-failed">
          Warning: Could not parse diff. Showing raw output.
        </p>
        <pre className="overflow-auto rounded bg-bg-muted p-3 font-mono text-xs text-text-secondary whitespace-pre">
          {diffText}
        </pre>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-text-muted">
        No changes in this scope.
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      {files.map((file) => {
        const filePath = file.newPath ?? file.oldPath ?? '';
        if (binaryFiles.has(filePath)) {
          return (
            <BinaryFileView
              key={`binary-${filePath}`}
              filePath={filePath}
            />
          );
        }
        return (
          <DiffFileItem
            key={`${file.oldRevision ?? ''}-${file.newRevision ?? ''}-${file.newPath}`}
            oldRevision={file.oldRevision}
            newRevision={file.newRevision}
            newPath={file.newPath}
            oldPath={file.oldPath}
            type={file.type}
            hunks={file.hunks}
            viewType={viewType}
            collapsed={collapsedFiles.has(filePath)}
            onToggleCollapse={() => toggleCollapse(filePath)}
          />
        );
      })}
      {/* Show any binary-only files that parseDiff may have omitted */}
      {Array.from(binaryFiles).filter(
        (p) => !files.some((f) => (f.newPath ?? f.oldPath) === p),
      ).map((p) => (
        <BinaryFileView key={`binary-only-${p}`} filePath={p} />
      ))}
    </div>
  );
}
