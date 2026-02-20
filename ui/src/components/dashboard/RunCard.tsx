import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import type { RunResponse, StepSummary, TaskSummary } from '../../types';
import { formatRelativeTime, formatDuration } from '../../lib/format';
import { outcomeColor, outcomeLabel } from '../../lib/outcome';
import { RunStatusBadge } from '../StatusBadge';
import { StepTimeline } from './StepTimeline';
import { CompactGradeRow } from '../CompactGradeRow';
import { AgentIcon } from '../AgentIcon';
import { useTransitionBack } from '../../hooks/useApi';

interface RunCardProps {
  run: RunResponse;
  routineName: string;
  expanded: boolean;
  onToggle: () => void;
  onStart: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
  onTaskClick?: (runId: string, task: TaskSummary) => void;
  loading?: { start?: boolean; pause?: boolean; resume?: boolean; cancel?: boolean; delete?: boolean };
}

/* ---------- Status icon (left side of collapsed row) ---------- */

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <svg
        className="h-4 w-4 text-status-completed shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2.5}
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    );
  }

  if (status === 'active') {
    return (
      <span
        className="inline-block h-2.5 w-2.5 rounded-full bg-status-active animate-pulse-dot shrink-0"
        aria-hidden="true"
      />
    );
  }

  if (status === 'paused') {
    return (
      <svg
        className="h-4 w-4 text-status-paused shrink-0"
        fill="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <rect x="6" y="4" width="4" height="16" rx="1" />
        <rect x="14" y="4" width="4" height="16" rx="1" />
      </svg>
    );
  }

  if (status === 'failed') {
    return (
      <svg
        className="h-4 w-4 text-status-failed shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2.5}
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    );
  }

  // draft or unknown
  return (
    <span
      className="inline-block h-2.5 w-2.5 rounded-full bg-status-pending shrink-0"
      aria-hidden="true"
    />
  );
}

/* ---------- Quick action buttons ---------- */

function QuickActions({
  run,
  onPause,
  onResume,
  onDelete,
  loading,
}: {
  run: RunResponse;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onDelete: (id: string) => void;
  loading?: RunCardProps['loading'];
}) {
  const btnBase =
    'px-3 py-1 text-[11px] font-semibold rounded border transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed';

  return (
    <div className="flex items-center gap-1.5">
      {run.status === 'active' && (
        <button
          onClick={e => { e.stopPropagation(); onPause(run.id); }}
          disabled={loading?.pause}
          className={btnBase + ' border-status-paused/40 text-status-paused hover:bg-status-paused/15'}
          aria-label="Pause run"
        >
          {loading?.pause ? 'Pausing...' : 'Pause'}
        </button>
      )}
      {run.status === 'paused' && (
        <button
          onClick={e => { e.stopPropagation(); onResume(run.id); }}
          disabled={loading?.resume}
          className={btnBase + ' border-accent-purple/40 text-accent-purple hover:bg-accent-purple/15'}
          aria-label="Resume run"
        >
          {loading?.resume ? 'Resuming...' : 'Resume'}
        </button>
      )}
      {run.status === 'failed' && (
        <button
          onClick={e => { e.stopPropagation(); onDelete(run.id); }}
          disabled={loading?.delete}
          className={btnBase + ' border-status-failed/40 text-status-failed hover:bg-status-failed/15'}
          aria-label="Delete run"
        >
          {loading?.delete ? 'Deleting...' : 'Delete'}
        </button>
      )}
    </div>
  );
}

/* ---------- Expanded footer action buttons ---------- */

function FooterActions({
  run,
  onStart,
  onPause,
  onResume,
  onCancel,
  onDelete,
  loading,
}: {
  run: RunResponse;
  onStart: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
  loading?: RunCardProps['loading'];
}) {
  const btnBase =
    'px-3 py-1.5 text-[11px] font-semibold rounded border transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

  return (
    <div className="flex items-center gap-1.5">
      {run.status === 'draft' && (
        <>
          <button
            onClick={() => onStart(run.id)}
            disabled={loading?.start}
            className={btnBase + ' border-accent-purple/40 text-accent-purple hover:bg-accent-purple/15'}
            aria-label="Start run"
          >
            {loading?.start ? 'Starting...' : 'Start'}
          </button>
          <button
            onClick={() => onDelete(run.id)}
            disabled={loading?.delete}
            className={btnBase + ' border-status-failed/40 text-status-failed hover:bg-status-failed/15'}
            aria-label="Delete run"
          >
            {loading?.delete ? 'Deleting...' : 'Delete'}
          </button>
        </>
      )}
      {run.status === 'active' && (
        <>
          <button
            onClick={() => onPause(run.id)}
            disabled={loading?.pause}
            className={btnBase + ' border-status-paused/40 text-status-paused hover:bg-status-paused/15'}
            aria-label="Pause run"
          >
            {loading?.pause ? 'Pausing...' : 'Pause'}
          </button>
          <button
            onClick={() => onCancel(run.id)}
            disabled={loading?.cancel}
            className={btnBase + ' border-status-failed/40 text-status-failed hover:bg-status-failed/15'}
            aria-label="Abort run"
          >
            {loading?.cancel ? 'Aborting...' : 'Abort Run'}
          </button>
        </>
      )}
      {run.status === 'paused' && (
        <>
          <button
            onClick={() => onResume(run.id)}
            disabled={loading?.resume}
            className={btnBase + ' border-accent-purple/40 text-accent-purple hover:bg-accent-purple/15'}
            aria-label="Resume run"
          >
            {loading?.resume ? 'Resuming...' : 'Resume'}
          </button>
          <button
            onClick={() => onCancel(run.id)}
            disabled={loading?.cancel}
            className={btnBase + ' border-status-failed/40 text-status-failed hover:bg-status-failed/15'}
            aria-label="Abort run"
          >
            {loading?.cancel ? 'Aborting...' : 'Abort Run'}
          </button>
        </>
      )}
      {(run.status === 'completed' || run.status === 'failed') && (
        <button
          onClick={() => onDelete(run.id)}
          disabled={loading?.delete}
          className={btnBase + ' border-status-failed/40 text-status-failed hover:bg-status-failed/15'}
          aria-label="Delete run"
        >
          {loading?.delete ? 'Deleting...' : 'Delete'}
        </button>
      )}
    </div>
  );
}

/* ---------- Duration badge ---------- */

function DurationBadge({ ms }: { ms: number }) {
  if (ms === 0) return null;
  return (
    <span className="inline-flex items-center rounded bg-bg-elevated px-2 py-0.5 text-[11px] font-mono text-text-muted">
      {formatDuration(ms)}
    </span>
  );
}

/* ---------- Chevron toggle ---------- */

function ChevronToggle({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={'h-4 w-4 text-text-muted transition-transform duration-200 ' + (expanded ? 'rotate-90' : '')}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  );
}

/* ---------- Revert step modal ---------- */

function RevertStepModal({
  stepNumber,
  stepTitle,
  onConfirm,
  onClose,
  isPending,
}: {
  stepNumber: number;
  stepTitle: string;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  isPending: boolean;
}) {
  const [reason, setReason] = useState('');

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="revert-modal-title"
        className="mx-4 w-full max-w-md rounded-xl border border-border bg-bg-card shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 pt-6 pb-4">
          <h3 id="revert-modal-title" className="text-base font-semibold text-text-primary">
            Revert to Step {stepNumber}: {stepTitle}?
          </h3>
          <p className="mt-2 text-sm text-text-secondary">
            All tasks in this step and every step after it will be reset to{' '}
            <span className="font-medium text-text-primary">pending</span>. The agents will
            rebuild from this point. This cannot be undone.
          </p>
          <div className="mt-4">
            <label htmlFor="revert-reason" className="mb-1.5 block text-xs font-medium text-text-secondary">
              Reason <span className="text-text-muted">(optional)</span>
            </label>
            <textarea
              id="revert-reason"
              rows={3}
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="Why are you reverting this step?"
              className="w-full resize-none rounded-md border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50"
            />
          </div>
        </div>
        <div className="flex justify-end gap-3 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-md bg-bg-elevated px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-bg-hover disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(reason)}
            disabled={isPending}
            className="rounded-md bg-status-paused/15 border border-status-paused/40 px-4 py-2 text-sm font-medium text-status-paused transition-colors hover:bg-status-paused/25 disabled:opacity-50"
          >
            {isPending ? 'Reverting…' : 'Revert step'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Task card for expanded view ---------- */

function TaskCard({
  runId,
  task,
  onClick,
  onRevertStep,
}: {
  runId: string;
  task: TaskSummary;
  onClick?: () => void;
  onRevertStep?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuAnchorRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuPanelRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number; origin: string } | null>(null);

  const updateMenuPosition = useCallback(() => {
    if (!menuOpen || !menuButtonRef.current) return;

    const triggerRect = menuButtonRef.current.getBoundingClientRect();
    const menuRect = menuPanelRef.current?.getBoundingClientRect();
    const menuWidth = menuRect?.width ?? 160;
    const menuHeight = menuRect?.height ?? 36;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const gap = 6;
    const margin = 8;

    const spaceAbove = triggerRect.top - margin;
    const spaceBelow = viewportHeight - triggerRect.bottom - margin;
    const openAbove = spaceAbove >= menuHeight + gap || spaceAbove > spaceBelow;

    let top = openAbove
      ? triggerRect.top - menuHeight - gap
      : triggerRect.bottom + gap;
    let left = triggerRect.right - menuWidth;

    top = Math.max(margin, Math.min(top, viewportHeight - menuHeight - margin));
    left = Math.max(margin, Math.min(left, viewportWidth - menuWidth - margin));

    setMenuPosition({
      top,
      left,
      origin: openAbove ? 'bottom right' : 'top right',
    });
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleOutside(e: MouseEvent) {
      const targetNode = e.target as Node;
      const clickedAnchor = menuAnchorRef.current?.contains(targetNode);
      const clickedPanel = menuPanelRef.current?.contains(targetNode);
      if (!clickedAnchor && !clickedPanel) {
        setMenuOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenuOpen(false);
    }
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const frame = requestAnimationFrame(updateMenuPosition);
    window.addEventListener('resize', updateMenuPosition);
    window.addEventListener('scroll', updateMenuPosition, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', updateMenuPosition);
      window.removeEventListener('scroll', updateMenuPosition, true);
    };
  }, [menuOpen, updateMenuPosition]);

  let bgClass = 'bg-bg-elevated/60 text-text-muted';
  if (task.status === 'completed') bgClass = 'bg-status-completed/10 text-status-completed';
  else if (task.status === 'building') bgClass = 'bg-status-active/10 text-status-active';
  else if (task.status === 'verifying') bgClass = 'bg-accent-purple/10 text-accent-purple';
  else if (task.status === 'recovering') bgClass = 'bg-amber-500/10 text-amber-600';
  else if (task.status === 'failed') bgClass = 'bg-status-failed/10 text-status-failed';
  else if (task.pending_action_type) bgClass = 'bg-yellow-100/60 text-yellow-800';

  return (
    <div
      className={
        'relative rounded px-2 py-1.5 text-[11px] font-medium ' + bgClass +
        (onClick ? ' cursor-pointer hover:ring-1 hover:ring-accent-purple/40 transition-shadow' : '')
      }
      onClick={onClick ? e => { e.stopPropagation(); onClick(); } : undefined}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onClick(); } } : undefined}
    >
      <div className="flex items-center justify-between gap-1">
        <div className="flex items-center gap-1.5 truncate">
          {task.pending_action_type && (
            <svg className="h-3 w-3 shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
            </svg>
          )}
          <span className="truncate">{task.title || task.config_id}</span>
        </div>
        {task.current_attempt > 1 && (
          <span className="text-text-muted font-mono text-[10px] shrink-0">
            x{task.current_attempt}
          </span>
        )}
      </div>
      {task.grade_summary.length > 0 && (
        <div className="mt-1">
          <CompactGradeRow grades={task.grade_summary} />
        </div>
      )}
      {task.attempts_summary.length > 1 ? (
        <div className="mt-1 space-y-0.5">
          {task.attempts_summary.map(att => {
            let displayLabel: string | null = null;
            let displayColor: string = '';

            if (att.outcome) {
              displayLabel = outcomeLabel(att.outcome);
              displayColor = outcomeColor(att.outcome);
            } else if (att.attempt_num < task.current_attempt) {
              displayLabel = 'Needs revision';
              displayColor = outcomeColor('revision_needed');
            } else {
              displayLabel = 'Building...';
              displayColor = 'text-status-active animate-pulse-dot';
            }

            return (
              <div key={att.attempt_num} className="flex items-center gap-1.5 text-[10px]">
                <span className="text-text-muted font-mono">#{att.attempt_num}</span>
                <span className={'font-medium ' + displayColor}>
                  {displayLabel}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-[10px] text-text-muted mt-0.5 capitalize">
          {task.status === 'recovering' ? 'Recovering\u2026' : task.status}
        </div>
      )}
      {task.pending_action_type === 'clarification' && (
        <div className="mt-1.5">
          <Link
            to={`/runs/${runId}?action=clarification&task_id=${task.id}`}
            onClick={(event) => event.stopPropagation()}
            className="inline-flex items-center rounded border border-status-paused/40 bg-status-paused/10 px-2 py-0.5 text-[10px] font-semibold text-status-paused hover:bg-status-paused/20 transition-colors"
          >
            Answer Questions
          </Link>
        </div>
      )}

      {/* Three-dot action menu — bottom-right, only for revertable tasks */}
      {onRevertStep && (
        <div
          ref={menuAnchorRef}
          className="absolute bottom-1.5 right-1.5"
          onClick={e => e.stopPropagation()}
        >
          <button
            ref={menuButtonRef}
            type="button"
            aria-label="Task actions"
            onClick={() => setMenuOpen(m => !m)}
            className="flex items-center justify-center h-5 w-5 rounded bg-black/10 text-text-muted/85 hover:bg-black/20 hover:text-text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-purple/50 transition-colors"
          >
            <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
              <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
            </svg>
          </button>
          {menuOpen && createPortal(
            <div
              ref={menuPanelRef}
              style={{
                top: menuPosition?.top ?? 8,
                left: menuPosition?.left ?? 8,
                transformOrigin: menuPosition?.origin ?? 'top right',
              }}
              className="fixed z-[80] min-w-[160px] rounded-md border border-border bg-bg-card shadow-lg py-1"
            >
              <button
                type="button"
                onClick={() => { setMenuOpen(false); onRevertStep(); }}
                className="w-full text-left px-3 py-1.5 text-[12px] text-text-primary hover:bg-bg-elevated transition-colors"
              >
                Revert to this step
              </button>
            </div>,
            document.body
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- Step column for expanded view ---------- */

function StepColumn({ step, index, isCurrent, runId, onTaskClick }: { step: StepSummary; index: number; isCurrent: boolean; runId: string; onTaskClick?: (runId: string, task: TaskSummary) => void }) {
  const completed = step.tasks.filter(t => t.status === 'completed').length;
  const total = step.tasks.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const hasFailed = step.tasks.some(t => t.status === 'failed');
  const canRevert = step.completed;
  const [revertModalOpen, setRevertModalOpen] = useState(false);
  const transitionBack = useTransitionBack(runId);

  let badgeClass = 'bg-transparent border border-border-hover text-text-muted';
  if (hasFailed) badgeClass = 'bg-status-failed text-white';
  else if (step.completed) badgeClass = 'bg-accent-purple text-white';
  else if (isCurrent) badgeClass = 'bg-status-active text-white animate-pulse-glow';

  let barColor = 'bg-border-hover';
  if (hasFailed) barColor = 'bg-status-failed';
  else if (step.completed) barColor = 'bg-accent-purple';
  else if (isCurrent) barColor = 'bg-status-active';

  async function handleRevert(reason: string) {
    await transitionBack.mutateAsync({ target_step_index: index, reason: reason.trim() || undefined });
    setRevertModalOpen(false);
  }

  return (
    <div className="group flex-1 min-w-[140px] max-w-[240px]">
      {/* Step header */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className={
            'flex items-center justify-center rounded font-mono text-[10px] font-bold leading-none w-7 h-[22px] ' +
            badgeClass
          }
        >
          S{index + 1}
        </div>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-secondary truncate">
          {step.title || step.config_id}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-1 rounded-full bg-bg-elevated mb-3 overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div
          className={'h-full rounded-full transition-all duration-300 ' + barColor}
          style={{ width: pct + '%' }}
        />
      </div>

      {/* Task cards */}
      <div className="space-y-1.5">
        {step.tasks.map(task => (
          <TaskCard
            key={task.id}
            runId={runId}
            task={task}
            onClick={onTaskClick ? () => onTaskClick(runId, task) : undefined}
            onRevertStep={canRevert ? () => setRevertModalOpen(true) : undefined}
          />
        ))}
      </div>

      {revertModalOpen && (
        <RevertStepModal
          stepNumber={index + 1}
          stepTitle={step.title || step.config_id}
          onConfirm={handleRevert}
          onClose={() => setRevertModalOpen(false)}
          isPending={transitionBack.isPending}
        />
      )}
    </div>
  );
}

/* ---------- Collapsed row ---------- */

function CollapsedRow(props: RunCardProps) {
  const { run, routineName, onToggle, loading } = props;
  const navigate = useNavigate();

  // Count pending human actions (task-level + step-gate approvals)
  const pendingActionsCount = run.steps
    .flatMap(step => step.tasks)
    .filter(task => task.pending_action_type !== null).length;
  const currentStep = run.steps[run.current_step_index];
  const hasCurrentStepApprovalPending =
    !!currentStep &&
    currentStep.has_approval_gate &&
    currentStep.approval_status === 'pending';
  const totalPendingActions = pendingActionsCount + (hasCurrentStepApprovalPending ? 1 : 0);
  const clarificationTaskId = currentStep?.tasks.find(
    (task) => task.pending_action_type === 'clarification',
  )?.id;
  const approvalTaskId = hasCurrentStepApprovalPending ? currentStep?.tasks[0]?.id : undefined;

  return (
    <div
      className="flex min-w-0 items-center gap-3 px-4 py-3 cursor-pointer"
      onClick={onToggle}
      role="button"
      tabIndex={0}
      aria-expanded={false}
      aria-label={`Expand run ${routineName}`}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
        {/* Status icon */}
        <StatusIcon status={run.status} />

        {/* Status badge */}
        <RunStatusBadge status={run.status} />

        {/* Run name */}
        <span className="min-w-0 truncate text-sm font-semibold text-text-primary">
          {routineName}
        </span>

        {/* Meta line */}
        <div className="ml-1 flex min-w-0 items-center gap-2 overflow-hidden font-mono text-[11px] text-text-muted">
          <span className="truncate" title={run.id}>{run.id.slice(0, 8)}</span>
          {run.routine_id && (
            <>
              <span className="text-border-hover">|</span>
              <span className="truncate">{run.routine_id}</span>
            </>
          )}
          <span className="text-border-hover">|</span>
          <span className="truncate" title={run.repo_name}>{run.repo_name}</span>
          {run.agent_icon !== 'none' && (
            <>
              <span className="text-border-hover">|</span>
              <span className="flex items-center gap-1.5">
                <AgentIcon icon={run.agent_icon} className="h-3.5 w-3.5" />
                <span className="truncate">{run.agent_type_display}</span>
              </span>
            </>
          )}
        </div>
      </div>

      <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-2">
        {/* Step badges */}
        <div className="w-0 flex-1 overflow-x-auto scrollbar-dark">
          <StepTimeline
            runId={run.id}
            steps={run.steps}
            currentStepIndex={run.current_step_index}
            pendingCount={totalPendingActions}
            onPendingClick={() => {
              navigate(
                clarificationTaskId
                  ? `/runs/${run.id}?action=clarification&task_id=${clarificationTaskId}`
                  : approvalTaskId
                    ? `/runs/${run.id}?action=approval&task_id=${approvalTaskId}`
                  : `/runs/${run.id}`,
              );
            }}
          />
        </div>

        {/* Duration */}
        <DurationBadge ms={run.total_duration_ms} />

        {/* Quick actions */}
        <div className="shrink-0">
          <QuickActions
            run={run}
            onPause={props.onPause}
            onResume={props.onResume}
            onDelete={props.onDelete}
            loading={loading}
          />
        </div>

        {/* Chevron */}
        <div className="shrink-0">
          <ChevronToggle expanded={false} />
        </div>
      </div>
    </div>
  );
}

/* ---------- Expanded view ---------- */

function ExpandedView(props: RunCardProps) {
  const { run, routineName, onToggle, onTaskClick, loading } = props;

  const currentStep = run.steps[run.current_step_index];
  const clarificationTaskId = currentStep?.tasks.find(
    (task) => task.pending_action_type === 'clarification',
  )?.id;
  const hasCurrentStepApprovalPending =
    !!currentStep &&
    currentStep.has_approval_gate &&
    currentStep.approval_status === 'pending';
  const approvalTaskId = hasCurrentStepApprovalPending ? currentStep?.tasks[0]?.id : undefined;

  return (
    <div>
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer border-b border-border"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={true}
        aria-label={`Collapse run ${routineName}`}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); } }}
      >
        {/* Status icon */}
        <StatusIcon status={run.status} />

        {/* Status badge */}
        <RunStatusBadge status={run.status} />

        {/* Run name */}
        <span className="text-sm font-semibold text-text-primary truncate shrink-0">
          {routineName}
        </span>

        {/* Extended meta */}
        <div className="flex items-center gap-2 text-[11px] text-text-muted font-mono ml-1 min-w-0 overflow-hidden">
          <span className="truncate" title={run.id}>{run.id.slice(0, 8)}</span>
          {run.routine_id && (
            <>
              <span className="text-border-hover">|</span>
              <span className="truncate">{run.routine_id}</span>
            </>
          )}
          <span className="text-border-hover">|</span>
          <span className="truncate" title={run.repo_name}>{run.repo_name}</span>
          {run.agent_icon !== 'none' && (
            <>
              <span className="text-border-hover">|</span>
              <span className="flex items-center gap-1.5">
                <AgentIcon icon={run.agent_icon} className="h-3.5 w-3.5" />
                <span className="truncate">{run.agent_type_display}</span>
              </span>
            </>
          )}
          {run.started_at && (
            <>
              <span className="text-border-hover">|</span>
              <span>started {formatRelativeTime(run.started_at)}</span>
            </>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Duration */}
        <DurationBadge ms={run.total_duration_ms} />

        {/* Quick actions */}
        <QuickActions
          run={run}
          onPause={props.onPause}
          onResume={props.onResume}
          onDelete={props.onDelete}
          loading={loading}
        />

        {/* Chevron */}
        <ChevronToggle expanded={true} />
      </div>

      {/* Step columns + Footer (animated) */}
      <div className="animate-slide-down overflow-hidden">
      {run.steps.length > 0 && (
        <div className="px-4 py-4">
          <div className="flex gap-4 overflow-x-auto scrollbar-dark">
            {run.steps.map((step, i) => (
              <StepColumn
                key={step.id}
                step={step}
                index={i}
                isCurrent={i === run.current_step_index}
                runId={run.id}
                onTaskClick={onTaskClick}
              />
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-border">
        <div className="flex items-center gap-3">
          <Link
            to={'/runs/' + run.id}
            className="text-[11px] font-semibold text-accent-purple hover:text-accent-purple/80 transition-colors"
          >
            Open Detailed View
          </Link>
          {clarificationTaskId && (
            <Link
              to={`/runs/${run.id}?action=clarification&task_id=${clarificationTaskId}`}
              className="text-[11px] font-semibold text-status-paused hover:text-status-paused/80 transition-colors"
            >
              Answer Questions
            </Link>
          )}
          {!clarificationTaskId && approvalTaskId && (
            <Link
              to={`/runs/${run.id}?action=approval&task_id=${approvalTaskId}`}
              className="text-[11px] font-semibold text-status-paused hover:text-status-paused/80 transition-colors"
            >
              Review Approval
            </Link>
          )}
        </div>
        <FooterActions
          run={run}
          onStart={props.onStart}
          onPause={props.onPause}
          onResume={props.onResume}
          onCancel={props.onCancel}
          onDelete={props.onDelete}
          loading={loading}
        />
      </div>
      </div>
    </div>
  );
}

/* ---------- Main export ---------- */

export function RunCard(props: RunCardProps) {
  const { run, expanded } = props;

  const borderClass = run.status === 'active'
    ? 'border-status-active/30'
    : 'border-border hover:border-border-hover';

  return (
    <div
      className={
        'rounded-lg border bg-bg-card transition-colors ' +
        borderClass +
        (run.status === 'active' ? ' animate-pulse-glow' : '')
      }
    >
      {expanded ? <ExpandedView {...props} /> : <CollapsedRow {...props} />}
    </div>
  );
}
