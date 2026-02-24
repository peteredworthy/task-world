import { useEffect } from 'react';
import type { PruneSelection } from '../../types/review';
import { usePrunePreview, usePruneApply } from '../../hooks/useReview';
import { ApiError } from '../../api/client';
import { DiffViewer } from './DiffViewer';

interface PrunePreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  runId: string;
  selection: PruneSelection;
  onApplied?: () => void;
}

/**
 * Modal that shows a summary of what will be pruned (files/hunks/lines affected)
 * along with the resulting diff. Provides Apply and Cancel actions.
 */
export function PrunePreviewModal({ isOpen, onClose, runId, selection, onApplied }: PrunePreviewModalProps) {
  const preview = usePrunePreview(runId);
  const apply = usePruneApply(runId);

  // Fetch preview whenever the modal opens
  useEffect(() => {
    if (isOpen && selection.files.length > 0) {
      preview.mutate(selection);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleApply = () => {
    apply.mutate(selection, {
      onSuccess: () => {
        onApplied?.();
        onClose();
      },
    });
  };

  const previewError = preview.error instanceof ApiError ? preview.error.message : preview.error ? 'Failed to load preview.' : null;
  const applyError = apply.error instanceof ApiError ? apply.error.message : apply.error ? 'Failed to apply prune.' : null;

  const data = preview.data;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />

      {/* Dialog */}
      <div className="relative z-10 flex flex-col w-[90vw] max-w-3xl max-h-[85vh] rounded-lg border border-border bg-bg-primary shadow-xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 shrink-0 border-b border-border bg-bg-elevated px-4 py-3">
          <span className="flex-1 font-medium text-sm text-text-primary">Prune Preview</span>

          {/* Close button */}
          <button
            type="button"
            onClick={onClose}
            disabled={apply.isPending}
            className="rounded p-1 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors disabled:opacity-40"
            aria-label="Close prune preview"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-auto">
          {preview.isPending ? (
            <div className="flex items-center justify-center h-48">
              <p className="text-sm text-text-muted">Loading preview…</p>
            </div>
          ) : previewError ? (
            <div className="flex flex-col items-center justify-center h-48 gap-3">
              <p className="text-sm text-status-failed">{previewError}</p>
              <button
                type="button"
                onClick={() => preview.mutate(selection)}
                className="rounded border border-status-failed/40 px-3 py-1.5 text-xs text-status-failed hover:bg-status-failed/10 transition-colors"
              >
                Retry
              </button>
            </div>
          ) : data ? (
            <div className="flex flex-col">
              {/* Summary stats */}
              <div className="shrink-0 border-b border-border bg-bg-elevated px-4 py-3">
                <p className="text-xs text-text-secondary mb-2">
                  The following changes will be removed and committed to the run branch:
                </p>
                <div className="flex items-center gap-4">
                  <StatBadge label="files" value={data.files_affected} />
                  <StatBadge label="hunks" value={data.hunks_removed} />
                  <StatBadge label="lines" value={data.lines_removed} />
                </div>
              </div>

              {/* Resulting diff */}
              <div className="p-4">
                <p className="text-xs font-medium text-text-secondary mb-2 uppercase tracking-wide">
                  Resulting diff after prune
                </p>
                {data.resulting_diff ? (
                  <DiffViewer diffText={data.resulting_diff} viewType="unified" />
                ) : (
                  <p className="text-sm text-text-muted italic">No remaining diff — all changes will be removed.</p>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-border bg-bg-elevated px-4 py-3 flex items-center justify-between gap-3">
          {/* Apply error */}
          {applyError && (
            <p className="text-xs text-status-failed flex-1">{applyError}</p>
          )}
          {!applyError && <div className="flex-1" />}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={apply.isPending}
              className="rounded border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-bg-muted hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApply}
              disabled={!data || apply.isPending || preview.isPending}
              className="rounded border border-amber-500/50 bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-400 transition-colors hover:bg-amber-500/25 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {apply.isPending ? 'Applying…' : 'Apply Prune'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-center gap-1 text-xs">
      <span className="font-semibold text-text-primary">{value}</span>
      <span className="text-text-muted">{label} affected</span>
    </span>
  );
}
