import { useEffect, useRef, useState } from 'react';
import { useResolveConflict } from '../../hooks/useReview';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { ConflictBlock } from './ConflictBlock';
import { ConfirmDialog } from '../ConfirmDialog';
import { Spinner } from '../Spinner';
import { ApiError } from '../../api/client';
import type { ConflictFile, BlockResolution } from '../../types/review';

interface ConflictResolverDialogProps {
  runId: string;
  files: ConflictFile[];
  initialFileIndex?: number;
  isOpen: boolean;
  onClose: () => void;
}

export function ConflictResolverDialog({
  runId,
  files,
  initialFileIndex = 0,
  isOpen,
  onClose,
}: ConflictResolverDialogProps) {
  const [fileIndex, setFileIndex] = useState(initialFileIndex);
  // Map of filePath -> BlockResolution[]
  const [resolutions, setResolutions] = useState<Record<string, BlockResolution[]>>({});
  const [confirmResolveOpen, setConfirmResolveOpen] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const resolveConflict = useResolveConflict(runId);

  // Sync fileIndex when initialFileIndex changes (e.g. caller opens a different file)
  useEffect(() => {
    if (isOpen) {
      setFileIndex(initialFileIndex);
    }
  }, [isOpen, initialFileIndex]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !confirmResolveOpen) onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose, confirmResolveOpen]);

  // Scroll lock
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  useFocusTrap(dialogRef, isOpen && !confirmResolveOpen);

  if (!isOpen || files.length === 0) return null;

  const clampedIndex = Math.min(fileIndex, files.length - 1);
  const currentFile = files[clampedIndex];
  const currentResolutions = resolutions[currentFile.path] ?? [];

  const allBlocksResolved =
    currentFile.blocks.length > 0 &&
    currentFile.blocks.every((b) =>
      currentResolutions.some((r) => r.block_index === b.index),
    );

  function handleBlockResolve(resolution: BlockResolution) {
    setResolutions((prev) => {
      const existing = prev[currentFile.path] ?? [];
      const filtered = existing.filter((r) => r.block_index !== resolution.block_index);
      return { ...prev, [currentFile.path]: [...filtered, resolution] };
    });
  }

  function handleMarkResolved() {
    setConfirmResolveOpen(true);
  }

  async function handleConfirmResolve() {
    setConfirmResolveOpen(false);
    setResolveError(null);
    try {
      await resolveConflict.mutateAsync({
        filePath: currentFile.path,
        resolutions: currentResolutions,
      });
      // Move to next unresolved file if any
      const nextUnresolved = files.findIndex(
        (f, i) => i !== clampedIndex && f.status === 'unresolved',
      );
      if (nextUnresolved !== -1) {
        setFileIndex(nextUnresolved);
      }
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : 'Failed to mark file resolved.';
      setResolveError(message);
    }
  }

  function handlePrev() {
    setFileIndex((i) => Math.max(0, i - 1));
    setResolveError(null);
  }

  function handleNext() {
    setFileIndex((i) => Math.min(files.length - 1, i + 1));
    setResolveError(null);
  }

  const unresolvedCount = files.filter((f) => f.status === 'unresolved').length;

  const titleId = 'conflict-resolver-title';

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center">
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/80" onClick={onClose} />

        {/* Dialog */}
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className="relative z-10 flex flex-col w-[95vw] h-[92vh] rounded-xl border border-border bg-bg-primary shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="shrink-0 flex items-center gap-3 border-b border-border bg-bg-elevated px-4 py-3">
            {/* Title + file path */}
            <div className="flex-1 min-w-0">
              <span id={titleId} className="text-sm font-semibold text-text-primary">
                Conflict Resolver
              </span>
              <span className="ml-2 font-mono text-xs text-text-muted truncate">
                — {currentFile.path}
              </span>
            </div>

            {/* Merge readiness */}
            {unresolvedCount === 0 ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-status-success">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M13 4L6 11L3 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                All conflicts resolved
              </span>
            ) : (
              <span className="text-xs text-text-muted">
                {unresolvedCount} unresolved {unresolvedCount === 1 ? 'file' : 'files'}
              </span>
            )}

            {/* Prev / Next file navigation */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handlePrev}
                disabled={clampedIndex === 0}
                className="rounded p-1.5 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors disabled:opacity-30"
                aria-label="Previous file"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <span className="text-xs text-text-muted tabular-nums">
                {clampedIndex + 1} / {files.length}
              </span>
              <button
                type="button"
                onClick={handleNext}
                disabled={clampedIndex === files.length - 1}
                className="rounded p-1.5 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors disabled:opacity-30"
                aria-label="Next file"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M6 12L10 8L6 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>

            {/* Close */}
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors"
              aria-label="Close conflict resolver"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {/* File tab strip */}
          {files.length > 1 && (
            <div className="shrink-0 flex items-center gap-0.5 overflow-x-auto border-b border-border bg-bg-elevated px-3 py-1.5">
              {files.map((file, i) => (
                <button
                  key={file.path}
                  type="button"
                  onClick={() => { setFileIndex(i); setResolveError(null); }}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-mono shrink-0 transition-colors ${
                    i === clampedIndex
                      ? 'bg-bg-primary text-text-primary border border-border shadow-sm'
                      : 'text-text-muted hover:bg-bg-muted hover:text-text-secondary'
                  }`}
                  title={file.path}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                      file.status === 'resolved' ? 'bg-status-success' : 'bg-status-failed'
                    }`}
                  />
                  <span className="max-w-[160px] truncate">{file.path}</span>
                </button>
              ))}
            </div>
          )}

          {/* Content: conflict blocks */}
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {currentFile.blocks.length === 0 ? (
              <div className="flex items-center justify-center h-full">
                <p className="text-sm text-text-muted">No conflict blocks in this file.</p>
              </div>
            ) : (
              currentFile.blocks.map((block) => (
                <ConflictBlock
                  key={block.index}
                  block={block}
                  resolution={currentResolutions.find((r) => r.block_index === block.index)}
                  onResolve={handleBlockResolve}
                />
              ))
            )}
          </div>

          {/* Footer */}
          <div className="shrink-0 border-t border-border bg-bg-elevated px-4 py-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              {resolveError && (
                <p className="text-xs text-status-failed truncate">{resolveError}</p>
              )}
              {currentFile.status === 'resolved' && !resolveError && (
                <span className="inline-flex items-center gap-1 text-xs text-status-success">
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M13 4L6 11L3 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  File resolved
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {/* Prev / Next shortcuts in footer */}
              <button
                type="button"
                onClick={handlePrev}
                disabled={clampedIndex === 0}
                className="px-3 py-1.5 text-xs text-text-secondary border border-border rounded-md hover:bg-bg-hover transition-colors disabled:opacity-30"
              >
                ← Prev file
              </button>
              <button
                type="button"
                onClick={handleNext}
                disabled={clampedIndex === files.length - 1}
                className="px-3 py-1.5 text-xs text-text-secondary border border-border rounded-md hover:bg-bg-hover transition-colors disabled:opacity-30"
              >
                Next file →
              </button>

              {/* Mark File Resolved */}
              <button
                type="button"
                onClick={handleMarkResolved}
                disabled={
                  !allBlocksResolved ||
                  currentFile.status === 'resolved' ||
                  resolveConflict.isPending
                }
                className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-white bg-status-success rounded-md hover:bg-status-success/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {resolveConflict.isPending ? (
                  <>
                    <Spinner className="h-4 w-4" />
                    <span>Resolving…</span>
                  </>
                ) : (
                  <span>Mark File Resolved</span>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Confirmation modal for marking resolved */}
      <ConfirmDialog
        open={confirmResolveOpen}
        title="Mark file as resolved?"
        message={`This will apply your chosen resolutions to "${currentFile.path}" and mark it as resolved. This action cannot be undone from this dialog.`}
        confirmLabel="Mark Resolved"
        onConfirm={() => void handleConfirmResolve()}
        onCancel={() => setConfirmResolveOpen(false)}
      />
    </>
  );
}
