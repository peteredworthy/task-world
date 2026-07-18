import { useEffect, useRef, useState } from 'react';
import { useRecordGraphDecision } from '../hooks/useApi';
import { useFocusTrap } from '../hooks/useFocusTrap';
import type { GraphApprovalDecision, PendingGateDecision } from '../types';
import { Spinner } from './Spinner';

interface GraphDecisionModalProps {
  runId: string;
  gate: PendingGateDecision;
  onClose: () => void;
}

export function GraphDecisionModal({ runId, gate, onClose }: GraphDecisionModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const mutation = useRecordGraphDecision(runId);
  const [note, setNote] = useState('');
  const [pendingDecision, setPendingDecision] = useState<GraphApprovalDecision | null>(null);
  const isPending = mutation.isPending;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isPending, onClose]);

  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, []);

  useFocusTrap(dialogRef, true);

  async function submit(decision: GraphApprovalDecision) {
    if (isPending) return;
    setPendingDecision(decision);
    const reason = note.trim();
    try {
      await mutation.mutateAsync({
        decision_type: 'approval',
        node_id: gate.node_id,
        decision,
        decider: { kind: 'human', id: 'human-operator', role: 'operator' },
        ...(reason ? { reason } : {}),
      });
      onClose();
    } catch {
      setPendingDecision(null);
    }
  }

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-[70] flex items-center justify-center bg-black/80 p-4"
      onClick={isPending ? undefined : onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="graph-decision-title"
        className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-xl border border-border bg-bg-primary shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-border px-4 py-4 sm:px-6">
          <div>
            <h2 id="graph-decision-title" className="text-lg font-semibold text-text-primary">Review graph decision</h2>
            <p className="mt-1 text-sm text-text-muted">Approve or reject this human gate after reviewing its consequences.</p>
          </div>
          <button
            type="button"
            aria-label="Close"
            disabled={isPending}
            onClick={onClose}
            className="rounded-md p-1 text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
          <div className="rounded-lg border border-accent-purple/20 bg-accent-purple/5 p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-text-muted">Prompt</div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-text-primary">{gate.prompt ?? 'Review this human gate.'}</p>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-text-primary">Consequence</h3>
            <p className="mt-1 text-sm text-text-secondary">
              {gate.consequence_summary ?? 'Approval allows dependent graph work to continue. Rejection records the gate as rejected.'}
            </p>
          </div>
          <div>
            <label htmlFor="graph-decision-note" className="mb-2 block text-sm font-medium text-text-secondary">Note (optional)</label>
            <textarea
              id="graph-decision-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={4}
              disabled={isPending}
              placeholder="Add context for this decision..."
              className="w-full resize-none rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-primary focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 disabled:opacity-50"
            />
          </div>
          {mutation.isError && (
            <div role="alert" className="rounded-md border border-status-failed/20 bg-status-failed/10 px-3 py-2 text-sm text-status-failed">
              Failed to record decision. {mutation.error.message}
            </div>
          )}
        </div>

        <div className="flex flex-col-reverse gap-3 border-t border-border px-4 py-4 sm:flex-row sm:justify-end sm:px-6">
          <button
            type="button"
            disabled={isPending}
            onClick={onClose}
            className="rounded-md border border-border-hover px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isPending}
            onClick={() => void submit('rejected')}
            className="flex items-center justify-center gap-2 rounded-md bg-status-failed px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-status-failed/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingDecision === 'rejected' && <Spinner className="h-4 w-4" />}
            {pendingDecision === 'rejected' ? 'Rejecting...' : 'Reject'}
          </button>
          <button
            type="button"
            disabled={isPending}
            onClick={() => void submit('approved')}
            className="flex items-center justify-center gap-2 rounded-md bg-status-completed px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-status-completed/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pendingDecision === 'approved' && <Spinner className="h-4 w-4" />}
            {pendingDecision === 'approved' ? 'Approving...' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  );
}
