import { useState, useEffect, useRef, useMemo } from 'react';
import type { ViewType } from 'react-diff-view';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useApproveTask, useApproveStep, useRejectTask } from '../../hooks/useApproval';
import { useDiff } from '../../hooks/useReview';
import { DiffViewer } from '../review/DiffViewer';
import { Spinner } from '../Spinner';
import type { PendingAction } from '../../types/clarifications';

interface ApprovalReviewDialogProps {
  open: boolean;
  onClose: () => void;
  pendingAction: PendingAction;
  runId: string;
}

export function ApprovalReviewDialog({
  open,
  onClose,
  pendingAction,
  runId,
}: ApprovalReviewDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const approveTaskMutation = useApproveTask(runId, pendingAction.task_id);
  const approveStepMutation = useApproveStep(runId, pendingAction.step_id);
  const approveMutation = pendingAction.is_gate_approval ? approveStepMutation : approveTaskMutation;
  const rejectMutation = useRejectTask(runId, pendingAction.task_id);

  const [comment, setComment] = useState('');
  const [viewType, setViewType] = useState<ViewType>('unified');
  const [expandAllSignal, setExpandAllSignal] = useState(0);
  const [collapseAllSignal, setCollapseAllSignal] = useState(0);

  // Fetch aggregate diff for all changes
  const { data: diffData, isLoading: isDiffLoading } = useDiff(
    open ? runId : undefined,
    'aggregate',
  );

  const diffText = diffData?.diff ?? '';

  // Count changed files from diff text
  const fileCount = useMemo(() => {
    if (!diffText) return 0;
    return (diffText.match(/^diff --git /gm) ?? []).length;
  }, [diffText]);

  // Escape key to close
  useEffect(() => {
    if (!open) return;
    const isPending = approveMutation.isPending || rejectMutation.isPending;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose, approveMutation.isPending, rejectMutation.isPending]);

  // Scroll lock
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const isPending = approveMutation.isPending || rejectMutation.isPending;

  async function handleApprove() {
    if (isPending) return;
    try {
      await approveMutation.mutateAsync({
        comment: comment.trim() || undefined,
      });
      setComment('');
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  async function handleReject() {
    if (isPending) return;
    try {
      await rejectMutation.mutateAsync({
        reason: comment.trim() || undefined,
      });
      setComment('');
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70"
        onClick={isPending ? undefined : onClose}
      />

      {/* Full-screen dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Review changes and approve"
        className="relative z-10 flex flex-col w-full h-full sm:w-[95vw] sm:h-[92vh] sm:rounded-lg border border-border bg-bg-primary shadow-xl overflow-hidden"
      >
        {/* ── Approval header ──────────────────────────────────────── */}
        <div className="shrink-0 border-b border-border bg-bg-elevated">
          <div className="flex items-start gap-4 px-4 py-3">
            {/* Left: instructions */}
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-semibold text-text-primary">
                Review Changes
              </h2>
              {pendingAction.approval_prompt && (
                <p className="text-xs text-text-secondary mt-1 whitespace-pre-wrap line-clamp-3">
                  {pendingAction.approval_prompt}
                </p>
              )}
            </div>

            {/* Center: comment input */}
            <div className="w-80 shrink-0">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Add a comment (optional)..."
                rows={2}
                className="w-full rounded-md border border-border bg-bg-card px-3 py-1.5 text-xs text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
              />
            </div>

            {/* Right: action buttons */}
            <div className="flex items-center gap-2 shrink-0">
              {!pendingAction.is_gate_approval && (
                <button
                  type="button"
                  onClick={handleReject}
                  disabled={isPending}
                  className="px-4 py-1.5 text-xs font-medium text-white bg-status-failed rounded-md hover:bg-status-failed/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
                >
                  {rejectMutation.isPending ? (
                    <>
                      <Spinner className="h-3.5 w-3.5" />
                      <span>Rejecting...</span>
                    </>
                  ) : (
                    <>
                      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                      <span>Reject</span>
                    </>
                  )}
                </button>
              )}
              <button
                type="button"
                onClick={handleApprove}
                disabled={isPending}
                className="px-4 py-1.5 text-xs font-medium text-white bg-status-completed rounded-md hover:bg-status-completed/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
              >
                {approveMutation.isPending ? (
                  <>
                    <Spinner className="h-3.5 w-3.5" />
                    <span>Approving...</span>
                  </>
                ) : (
                  <>
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    <span>Approve</span>
                  </>
                )}
              </button>

              {/* Close button */}
              <button
                type="button"
                onClick={isPending ? undefined : onClose}
                disabled={isPending}
                className="rounded p-1.5 text-text-muted hover:bg-bg-muted hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed ml-1"
                aria-label="Close review dialog"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </div>

          {/* Error states */}
          {(approveMutation.isError || rejectMutation.isError) && (
            <div className="px-4 pb-2">
              <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-1.5">
                <p className="text-xs text-status-failed">
                  {approveMutation.isError ? 'Failed to approve.' : 'Failed to reject.'} Please try again.
                </p>
              </div>
            </div>
          )}

          {/* Toolbar: file count, view mode, expand/collapse */}
          <div className="flex items-center gap-2 px-4 py-2 border-t border-border/50">
            <span className="text-[11px] text-text-muted flex-1">
              {isDiffLoading ? 'Loading changes...' : `${fileCount} file${fileCount !== 1 ? 's' : ''} changed`}
            </span>

            {/* Expand/Collapse All */}
            <div className="flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
              <button
                type="button"
                onClick={() => setExpandAllSignal((s) => s + 1)}
                className="rounded px-2 py-0.5 text-[11px] text-text-muted hover:text-text-secondary transition-colors"
              >
                Expand All
              </button>
              <button
                type="button"
                onClick={() => setCollapseAllSignal((s) => s + 1)}
                className="rounded px-2 py-0.5 text-[11px] text-text-muted hover:text-text-secondary transition-colors"
              >
                Collapse All
              </button>
            </div>

            {/* View mode toggle */}
            <div className="flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
              <button
                type="button"
                onClick={() => setViewType('unified')}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  viewType === 'unified'
                    ? 'bg-bg-elevated text-text-primary shadow-sm'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                Inline
              </button>
              <button
                type="button"
                onClick={() => setViewType('split')}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  viewType === 'split'
                    ? 'bg-bg-elevated text-text-primary shadow-sm'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                Split
              </button>
            </div>
          </div>
        </div>

        {/* ── Diff content ─────────────────────────────────────────── */}
        <div className="flex-1 min-h-0 overflow-auto p-4">
          {isDiffLoading ? (
            <div className="flex flex-col gap-3" aria-label="Loading diff">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex flex-col gap-1.5">
                  <span className="skeleton h-3.5 w-48" />
                  {[85, 70, 90, 60, 75].map((w, j) => (
                    <span key={j} className="skeleton h-3" style={{ width: `${w}%` }} />
                  ))}
                </div>
              ))}
            </div>
          ) : diffText ? (
            <DiffViewer
              diffText={diffText}
              viewType={viewType}
              expandAllSignal={expandAllSignal}
              collapseAllSignal={collapseAllSignal}
            />
          ) : (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-text-muted">No changes to review.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
