import { useState, useEffect, useRef } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useApproveTask, useRejectTask } from '../../hooks/useApproval';
import { Spinner } from '../Spinner';
import type { PendingAction } from '../../types/clarifications';

interface ApprovalModalProps {
  open: boolean;
  onClose: () => void;
  pendingAction: PendingAction;
  runId: string;
}

export function ApprovalModal({
  open,
  onClose,
  pendingAction,
  runId,
}: ApprovalModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const approveMutation = useApproveTask(runId, pendingAction.task_id);
  const rejectMutation = useRejectTask(runId, pendingAction.task_id);

  const [comment, setComment] = useState('');

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
      setComment(''); // Reset on success
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
      setComment(''); // Reset on success
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  function handleClose() {
    if (!isPending) {
      setComment(''); // Reset on close
      onClose();
    }
  }

  const titleId = 'approval-modal-title';

  // Simple markdown-like rendering for summary artifact
  function renderSummary(text: string) {
    // Split by newlines and render with basic formatting
    const lines = text.split('\n');
    return lines.map((line, idx) => {
      // Headers (lines starting with #)
      if (line.startsWith('### ')) {
        return (
          <h4 key={idx} className="text-sm font-semibold text-text-primary mt-3 mb-1">
            {line.substring(4)}
          </h4>
        );
      }
      if (line.startsWith('## ')) {
        return (
          <h3 key={idx} className="text-base font-semibold text-text-primary mt-4 mb-2">
            {line.substring(3)}
          </h3>
        );
      }
      if (line.startsWith('# ')) {
        return (
          <h2 key={idx} className="text-lg font-semibold text-text-primary mt-4 mb-2">
            {line.substring(2)}
          </h2>
        );
      }
      // List items (lines starting with - or *)
      if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        return (
          <li key={idx} className="text-sm text-text-secondary ml-4">
            {line.trim().substring(2)}
          </li>
        );
      }
      // Code blocks (lines with backticks)
      if (line.trim().startsWith('```')) {
        return null; // Skip code fence markers for now
      }
      if (line.trim().startsWith('`') && line.trim().endsWith('`')) {
        return (
          <code key={idx} className="text-xs bg-bg-elevated px-1.5 py-0.5 rounded font-mono text-text-primary">
            {line.trim().slice(1, -1)}
          </code>
        );
      }
      // Empty lines
      if (line.trim() === '') {
        return <div key={idx} className="h-2" />;
      }
      // Regular paragraphs
      return (
        <p key={idx} className="text-sm text-text-secondary">
          {line}
        </p>
      );
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={isPending ? undefined : handleClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[700px] mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div className="flex-1">
            <h2
              id={titleId}
              className="text-lg font-semibold text-text-primary"
            >
              Approval Required
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Review the agent's work and decide whether to approve or reject.
            </p>
          </div>
          <button
            type="button"
            onClick={isPending ? undefined : handleClose}
            disabled={isPending}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label="Close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {/* Approval Prompt */}
          {pendingAction.approval_prompt && (
            <div className="rounded-lg bg-accent-purple/5 border border-accent-purple/20 p-4">
              <div className="flex items-start gap-3">
                <div className="shrink-0 mt-0.5">
                  <svg
                    className="h-5 w-5 text-accent-purple"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                </div>
                <div className="flex-1">
                  <h3 className="text-sm font-semibold text-text-primary mb-1">
                    Review Instructions
                  </h3>
                  <p className="text-sm text-text-secondary whitespace-pre-wrap">
                    {pendingAction.approval_prompt}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Summary Artifact */}
          {pendingAction.summary_artifact && (
            <div>
              <h3 className="text-sm font-semibold text-text-primary mb-2">
                Summary
              </h3>
              <div className="rounded-lg bg-bg-card border border-border p-4 space-y-1 overflow-x-auto">
                {renderSummary(pendingAction.summary_artifact)}
              </div>
            </div>
          )}

          {/* Comment Input */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Comment (optional)
            </label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment or reason for your decision..."
              rows={4}
              className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
            />
          </div>

          {/* Error states */}
          {approveMutation.isError && (
            <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
              <p className="text-sm text-status-failed">
                Failed to approve. Please try again.
              </p>
            </div>
          )}
          {rejectMutation.isError && (
            <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
              <p className="text-sm text-status-failed">
                Failed to reject. Please try again.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border flex justify-end gap-3">
          <button
            type="button"
            onClick={handleClose}
            disabled={isPending}
            className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleReject}
            disabled={isPending}
            className="px-5 py-2 text-sm font-medium text-white bg-status-failed rounded-md hover:bg-status-failed/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {rejectMutation.isPending ? (
              <>
                <Spinner className="h-4 w-4" />
                <span>Rejecting...</span>
              </>
            ) : (
              <>
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                <span>Reject</span>
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={isPending}
            className="px-5 py-2 text-sm font-medium text-white bg-status-completed rounded-md hover:bg-status-completed/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {approveMutation.isPending ? (
              <>
                <Spinner className="h-4 w-4" />
                <span>Approving...</span>
              </>
            ) : (
              <>
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2.5}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                <span>Approve</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
