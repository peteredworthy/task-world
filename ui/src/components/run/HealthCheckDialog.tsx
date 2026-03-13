import { useRef, useEffect } from 'react';
import { useResumeRun } from '../../hooks/useApi';
import { Spinner } from '../Spinner';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import type { RunResponse } from '../../types';

interface HealthCheckDialogProps {
  open: boolean;
  run: RunResponse | null;
  onClose: () => void;
}

export function HealthCheckDialog({ open, run, onClose }: HealthCheckDialogProps) {
  const resumeRun = useResumeRun();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open);

  const isDirty = run?.pause_reason === 'health_check_dirty';
  const titleId = 'health-check-dialog-title';

  // Escape key to close
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  // Scroll lock
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!open || !run) return null;

  const submitting = resumeRun.isPending;

  async function handleContinueDirty() {
    if (!run) return;
    try {
      await resumeRun.mutateAsync({ runId: run.id, resumeStrategy: 'continue_dirty' });
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  async function handleResetWorktree() {
    if (!run) return;
    try {
      await resumeRun.mutateAsync({ runId: run.id, resumeStrategy: 'reset_worktree' });
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[520px] mx-4 max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-text-primary">
              {isDirty ? 'Worktree Has Uncommitted Changes' : 'Health Check Failed'}
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              {isDirty
                ? 'The worktree has uncommitted changes and the pre-run health check failed.'
                : 'The pre-run health check failed. Tests did not pass.'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover"
            aria-label="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Error detail */}
          {run.last_error && (
            <div className="rounded-lg bg-status-failed/5 border border-status-failed/20 p-3">
              <div className="text-xs font-medium text-status-failed mb-1">Error output</div>
              <pre className="text-xs text-text-muted font-mono whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                {run.last_error}
              </pre>
            </div>
          )}

          {/* Mutation error */}
          {resumeRun.isError && (
            <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
              <p className="text-sm text-status-failed">Failed to resume run. Please try again.</p>
            </div>
          )}

          {/* Actions */}
          <div className="space-y-3">
            <button
              onClick={handleContinueDirty}
              disabled={submitting}
              className="w-full px-4 py-3 text-sm font-medium text-white bg-accent-purple rounded-lg hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {submitting ? (
                <>
                  <Spinner />
                  <span>Resuming...</span>
                </>
              ) : (
                <>
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  <span>Continue Anyway (skip health check)</span>
                </>
              )}
            </button>

            {isDirty && (
              <button
                onClick={handleResetWorktree}
                disabled={submitting}
                className="w-full px-4 py-3 text-sm font-medium text-text-primary bg-bg-card border border-border rounded-lg hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                  <path d="M21 3v5h-5" />
                  <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                  <path d="M3 21v-5h5" />
                </svg>
                <span>Reset Worktree (discard changes)</span>
              </button>
            )}

            <button
              onClick={onClose}
              disabled={submitting}
              className="w-full px-4 py-3 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-lg hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
