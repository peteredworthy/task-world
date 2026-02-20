import { useEffect, useState, type FormEvent } from 'react';
import { ApiError } from '../../api/client';
import { useApproveStep } from '../../hooks/useApproval';
import type { StepSummary } from '../../types';
import { Spinner } from '../Spinner';

interface StepApprovalBannerProps {
  runId: string;
  step: StepSummary;
  isCurrentStep: boolean;
}

export function StepApprovalBanner({ runId, step, isCurrentStep }: StepApprovalBannerProps) {
  const [approvedBy, setApprovedBy] = useState('');
  const [comment, setComment] = useState('');
  const [errorToast, setErrorToast] = useState<string | null>(null);
  const approveStep = useApproveStep(runId, step.id);

  useEffect(() => {
    if (!errorToast) return;
    const timeoutId = window.setTimeout(() => setErrorToast(null), 3500);
    return () => window.clearTimeout(timeoutId);
  }, [errorToast]);

  if (!isCurrentStep || !step.has_approval_gate || step.approval_status !== 'pending') {
    return null;
  }

  const isPending = approveStep.isPending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending) return;

    try {
      await approveStep.mutateAsync({
        approved_by: approvedBy.trim(),
        comment: comment.trim() || undefined,
      });
      setComment('');
      setApprovedBy('');
      setErrorToast(null);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 404) {
          setErrorToast('Step not found or already approved');
          return;
        }
        if (error.status === 409) {
          setErrorToast('Step cannot be approved in its current state');
          return;
        }
      }
      setErrorToast('Failed to approve step');
    }
  }

  return (
    <>
      <form
        onSubmit={handleSubmit}
        className="mb-4 rounded-md border border-yellow-300 bg-yellow-50 px-4 py-3"
      >
        <div className="flex items-center gap-2">
          <svg className="h-4 w-4 text-yellow-700 shrink-0" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
          </svg>
          <p className="text-sm font-medium text-yellow-800">Step approval required</p>
        </div>

        <div className="mt-3 grid gap-3">
          <div>
            <label htmlFor={`approved-by-${step.id}`} className="mb-1 block text-xs font-medium text-yellow-900">
              Approved by
            </label>
            <input
              id={`approved-by-${step.id}`}
              type="text"
              required
              value={approvedBy}
              onChange={(event) => setApprovedBy(event.target.value)}
              placeholder="Reviewer name"
              className="w-full rounded-md border border-yellow-300 bg-white px-3 py-2 text-sm text-text-primary shadow-sm focus:border-yellow-500 focus:outline-none focus:ring-1 focus:ring-yellow-500/50"
            />
          </div>

          <div>
            <label htmlFor={`approval-comment-${step.id}`} className="mb-1 block text-xs font-medium text-yellow-900">
              Comment (optional)
            </label>
            <textarea
              id={`approval-comment-${step.id}`}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
              placeholder="Add context for this approval..."
              className="w-full rounded-md border border-yellow-300 bg-white px-3 py-2 text-sm text-text-primary shadow-sm focus:border-yellow-500 focus:outline-none focus:ring-1 focus:ring-yellow-500/50 resize-none"
            />
          </div>
        </div>

        <div className="mt-3 flex justify-end">
          <button
            type="submit"
            disabled={isPending || !approvedBy.trim()}
            className="inline-flex items-center gap-2 rounded-md border border-status-completed/40 bg-status-completed px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-status-completed/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isPending ? (
              <>
                <Spinner className="h-3.5 w-3.5" />
                <span>Approving...</span>
              </>
            ) : (
              'Approve Step'
            )}
          </button>
        </div>
      </form>

      {errorToast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed right-4 top-4 z-50 rounded-md border border-status-failed/40 bg-status-failed/15 px-3 py-2 text-sm text-status-failed shadow-lg"
        >
          {errorToast}
        </div>
      )}
    </>
  );
}
