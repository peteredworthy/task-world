import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { useRun, useRoutine, usePauseRun, useCancelRun, useMergeBack, useResumeRun, useSkipStep } from '../../hooks/useApi';
import { useBranchStatus } from '../../hooks/useReview';
import { useActivityStream } from '../../hooks/useActivityStream';
import { usePendingActions } from '../../hooks/usePendingActions';
import { WebSocketProvider } from '../../context/WebSocketContext';
import { ReviewMergeProvider } from '../../context/ReviewMergeContext';
import { useReviewMerge } from '../../context/useReviewMerge';
import { useWebSocketStatus } from '../../hooks/useWebSocketStatus';
import { RunStatusBadge } from '../StatusBadge';
import { ConnectionIndicator } from '../ConnectionIndicator';
import { AgentGuidancePanel } from '../guidance/AgentGuidancePanel';
import { ResumeDialog } from '../run/ResumeDialog';
import { ClarificationModal } from '../detail/ClarificationModal';
import { ApprovalModal } from '../detail/ApprovalModal';
import { ApprovalReviewDialog } from '../detail/ApprovalReviewDialog';
import { Spinner } from '../Spinner';
import { RecoveryPanel } from '../detail/RecoveryPanel';
import { BranchStatusPanel } from '../detail/BranchStatusPanel';
import { EnvFilesPanel } from '../detail/EnvFilesPanel';
import { getLastAgentError } from '../../lib/activity';
import { ApiError } from '../../api/client';
import { ReviewMergeTab } from '../review/ReviewMergeTab';
import { ModelCostBreakdown } from '../detail/ModelCostBreakdown';
import type { RunResponse } from '../../types';
import type { PendingAction } from '../../types/clarifications';

/** Detect if the run is stuck: active but a task has failed with no remaining attempts. */
function isRunStuck(run: RunResponse): { stuck: boolean; failedTask: string | null } {
  if (run.status !== 'active') return { stuck: false, failedTask: null };
  for (const step of run.steps) {
    const failed = step.tasks.find(
      t => !t.parent_task_id && t.status === 'failed' && t.current_attempt >= t.max_attempts,
    );
    if (failed) {
      return { stuck: true, failedTask: failed.title || failed.config_id };
    }
  }
  return { stuck: false, failedTask: null };
}

/** Find the current actionable step (skipping already completed steps). */
function findActionableStep(run: RunResponse): { step: RunResponse['steps'][0]; index: number } | null {
  let index = run.current_step_index;
  while (index < run.steps.length && run.steps[index].completed) {
    index++;
  }
  if (index < run.steps.length) {
    return { step: run.steps[index], index };
  }
  return null;
}

function getPauseReasonMessage(run: RunResponse): string {
  if (!run.pause_reason) return '';

  if (run.pause_reason === 'no_executor_running') {
    if (run.agent_type === 'user_managed') {
      return 'Paused — no managed executor is attached. Connect an external agent or resume with a managed runner.';
    }
    return 'Paused — no executor is running. Resume the run to start a managed runner.';
  }

  const messages: Record<string, string> = {
    server_shutdown: 'Paused — server restarted; resume will continue from the current task',
    executor_not_started: 'Paused — executor startup safety marker; this should clear automatically within a few seconds',
    agent_not_available: 'Paused — selected agent runner is not available',
    agent_execution_error: 'Paused — agent execution error',
    agent_exit_failure: 'Paused — agent exited with error',
    gate_blocked: 'Paused — checklist gate not satisfied',
    manual_gate: 'Paused — waiting at manual gate',
    recovery_loop: 'Paused — recovery loop detected',
    unexpected_error: 'Paused — unexpected error',
    agent_health_check_failed: 'Paused — agent health check failed',
    agent_not_running_on_startup: 'Paused — agent was not running when the server started',
    recovered: 'Paused — recovered from failure',
    recovery_triggered: 'Paused — recovery triggered',
    requirement_escalated: 'Paused — agent flagged an unfulfillable requirement',
    waiting_for_approval: 'Paused — waiting for step approval',
    awaiting_approval: 'Paused — waiting for step approval',
    awaiting_user_input: 'Paused — waiting for user input',
    fan_out_child_failed: 'Paused — one or more fan-out children failed',
    fan_out_orphaned: 'Paused — fan-out task needs recovery',
    rate_limit: 'Paused — API rate or credit limit hit',
    all_steps_complete_but_active: 'Paused — all steps complete but run stayed active',
    no_actionable_tasks: 'Paused — no actionable tasks in current step',
  };

  return messages[run.pause_reason] ?? `Paused (${run.pause_reason})`;
}

function RunDetailInner({ runId }: { runId: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: run, isLoading, error } = useRun(runId);
  // Skip standalone routine fetch when the routine is embedded in the run
  const { data: routine } = useRoutine(
    run?.routine_source === 'embedded' ? null : run?.routine_id
  );
  const { data: activityData } = useActivityStream(runId);
  const { data: pendingActionsData } = usePendingActions(runId);
  const taskPendingActions = useMemo(() => pendingActionsData?.pendingActions ?? [], [pendingActionsData]);
  const pendingActionsCount = pendingActionsData?.badgeCount ?? 0;
  const pendingClarificationAction =
    taskPendingActions.find(
      (action) => action.action_type === 'clarification' && action.clarification_request,
    ) ?? null;
  const primaryPendingAction =
    pendingClarificationAction ??
    taskPendingActions[0] ??
    null;
  const { status: wsStatus, reconnect: wsReconnect } = useWebSocketStatus();
  const pauseRun = usePauseRun();
  const cancelRun = useCancelRun();
  const mergeBack = useMergeBack();
  const resumeRun = useResumeRun();
  const skipStep = useSkipStep(runId);
  const { data: branchStatus } = useBranchStatus(runId);
  const { isPruneMode, onTogglePruneMode, onOpenBackMergeModal } = useReviewMerge();
  const [showResumeDialog, setShowResumeDialog] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mergeResult, setMergeResult] = useState<string | null>(null);
  const [dirtyWorkingTree, setDirtyWorkingTree] = useState<{ branch: string; dirty_files: string[] } | null>(null);
  const [selectedPendingAction, setSelectedPendingAction] = useState<PendingAction | null>(null);
  const [approvalReviewAction, setApprovalReviewAction] = useState<PendingAction | null>(null);
  const autoOpenedRef = useRef(false);

  const handleMutationError = useCallback((action: string) => (err: Error) => {
    const detail = err instanceof ApiError
      ? err.message
      : 'Something went wrong';
    setMutationError(`Failed to ${action} run: ${detail}`);
  }, []);

  useEffect(() => {
    if (taskPendingActions.length === 0 || selectedPendingAction) return;

    const action = searchParams.get('action');
    const taskId = searchParams.get('task_id');
    if (!action) return;

    let match: PendingAction | undefined;
    if (action === 'clarification') {
      match = taskPendingActions.find(
        (pendingAction) =>
          pendingAction.action_type === 'clarification' &&
          (!!pendingAction.clarification_request) &&
          (!taskId || pendingAction.task_id === taskId),
      );
    } else if (action === 'approval') {
      match = taskPendingActions.find(
        (pendingAction) =>
          pendingAction.action_type === 'approval' &&
          (!taskId || pendingAction.task_id === taskId),
      );
    }

    if (match) {
      setSelectedPendingAction(match);
      const next = new URLSearchParams(searchParams);
      next.delete('action');
      next.delete('task_id');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams, selectedPendingAction, taskPendingActions]);

  // Auto-open pending action modal on first load (when no URL action param)
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (!primaryPendingAction || selectedPendingAction) return;
    if (searchParams.get('action')) return; // URL param effect handles this case
    autoOpenedRef.current = true;
    setSelectedPendingAction(primaryPendingAction);
  }, [primaryPendingAction, selectedPendingAction, searchParams]);


  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="rounded-md bg-status-failed/10 border border-status-failed/30 p-4">
        <p className="text-sm text-status-failed">Failed to load run.</p>
        <Link to="/" className="text-sm text-accent-purple hover:text-accent-purple/80 mt-2 inline-block">
          Back to dashboard
        </Link>
      </div>
    );
  }

  const embeddedName = (run.routine_embedded as Record<string, unknown> | null)?.name as string | undefined;
  const routineName = routine?.name || embeddedName || run.routine_id || 'Run';
  const events = activityData?.events ?? [];

  // Check if the run is stuck (failed task blocking progress)
  const { stuck: isStuck, failedTask: stuckTaskName } = isRunStuck(run);

  // Check for agent errors (e.g. run paused because agent crashed)
  const agentError = (run.status === 'paused' || run.status === 'failed') && !pendingClarificationAction
    ? getLastAgentError(events)
    : null;

  // Find active task for guidance panel
  const activeTask = run.agent_type === 'user_managed'
    ? run.steps.flatMap(s => s.tasks).find(t => t.status === 'building' || t.status === 'verifying')
    : null;


  return (
    <div className="flex h-full">
      {/* Main content area */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="p-4 sm:p-6">
          {/* Breadcrumb */}
          <nav className="mb-4" aria-label="Breadcrumb">
            <Link
              to="/"
              className="text-sm text-text-muted hover:text-text-primary transition-colors"
            >
              {'\u2190'} Runs
            </Link>
            <span className="text-text-muted mx-2">/</span>
            <span className="text-sm text-text-secondary">{routineName}</span>
          </nav>

          {/* Title row */}
          <div className="flex items-start justify-between mb-1">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-text-primary">
                  {routineName}
                </h1>
                <RunStatusBadge status={run.status} />
                <ConnectionIndicator status={wsStatus} onReconnect={wsReconnect} />
              </div>
              {run.status === 'paused' && run.pause_reason && run.pause_reason !== 'manual_pause' && (
                <div className="mt-1.5 text-xs text-status-paused">
                  <div>{getPauseReasonMessage(run)}</div>
                  {run.last_error && (
                    <div className="mt-1 text-xs text-gray-400 font-mono truncate max-w-md" title={run.last_error}>
                      {run.last_error}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 shrink-0">
              {run.status === 'active' && (
                <button
                  onClick={() => {
                    setMutationError(null);
                    pauseRun.mutate(run.id, { onError: handleMutationError('pause') });
                  }}
                  disabled={pauseRun.isPending}
                  className="px-3 py-1.5 text-xs font-medium text-status-paused bg-status-paused/10 border border-status-paused/30 rounded-md hover:bg-status-paused/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  aria-label="Pause this run"
                >
                  {pauseRun.isPending ? 'Pausing...' : 'Pause'}
                </button>
              )}
              {run.status === 'paused' && (
                <button
                  onClick={() => setShowResumeDialog(true)}
                  className="px-3 py-1.5 text-xs font-medium text-text-primary bg-accent-purple rounded-md hover:bg-accent-purple/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  aria-label="Resume this run"
                >
                  Resume
                </button>
              )}
              {(run.status === 'active' || run.status === 'paused') && (
                <button
                  onClick={() => {
                    setMutationError(null);
                    cancelRun.mutate(run.id, { onError: handleMutationError('abort') });
                  }}
                  disabled={cancelRun.isPending}
                  className="px-3 py-1.5 text-xs font-medium text-status-failed bg-status-failed/10 border border-status-failed/30 rounded-md hover:bg-status-failed/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  aria-label="Abort this run"
                >
                  {cancelRun.isPending ? 'Aborting...' : 'Abort Run'}
                </button>
              )}
              {/* Back Merge button */}
              {run.worktree_path && (
                <button
                  type="button"
                  onClick={onOpenBackMergeModal}
                  className="rounded border border-border px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-bg-muted hover:text-text-primary transition-colors"
                  title="Merge target branch into run branch"
                >
                  Back Merge
                </button>
              )}

              {/* Prune Mode button */}
              {run.worktree_path && (
                <button
                  type="button"
                  onClick={onTogglePruneMode}
                  className={`rounded border px-3 py-1.5 text-xs font-medium transition-colors ${
                    isPruneMode
                      ? 'border-amber-500/50 bg-amber-500/15 text-amber-400 hover:bg-amber-500/25'
                      : 'border-border text-text-secondary hover:bg-bg-muted hover:text-text-primary'
                  }`}
                  title={isPruneMode ? 'Exit prune mode' : 'Enter prune mode to select changes for removal'}
                >
                  {isPruneMode ? 'Exit Prune Mode' : 'Prune Mode'}
                </button>
              )}

              {run.status === 'completed' && !mergeResult && (
                branchStatus?.ahead_count === 0 ? (
                  <span className="px-3 py-1.5 text-xs font-medium text-status-completed bg-status-completed/10 border border-status-completed/30 rounded-md">
                    Merged
                  </span>
                ) : (
                  <button
                    onClick={() => {
                      setMutationError(null);
                      setDirtyWorkingTree(null);
                      mergeBack.mutate(
                        { runId: run.id },
                        {
                          onSuccess: (data) => setMergeResult(data.message),
                          onError: (err: Error) => {
                            if (err instanceof ApiError && err.body && typeof err.body === 'object') {
                              const body = err.body as Record<string, unknown>;
                              if (body.error === 'dirty_working_tree') {
                                setDirtyWorkingTree({
                                  branch: body.branch as string,
                                  dirty_files: body.dirty_files as string[],
                                });
                                return;
                              }
                            }
                            handleMutationError('merge back')(err);
                          },
                        },
                      );
                    }}
                    disabled={mergeBack.isPending}
                    className="px-3 py-1.5 text-xs font-medium text-text-primary bg-status-completed/20 border border-status-completed/40 rounded-md hover:bg-status-completed/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    aria-label="Merge run branch back to source"
                  >
                    {mergeBack.isPending ? 'Merging...' : `Merge to ${run.source_branch || 'main'}`}
                  </button>
                )
              )}
            </div>
          </div>


          <>
          {/* Manual gate control panel */}
          {run.status === 'paused' && run.pause_reason === 'manual_gate' && (() => {
            const actionable = findActionableStep(run);
            if (!actionable) return null;

            return (
              <div className="mb-6 rounded-md border border-accent-purple/40 bg-accent-purple/10 px-4 py-3 flex items-start gap-3">
                <svg className="h-5 w-5 text-accent-purple shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-accent-purple">Manual gate: Step {actionable.index + 1}</p>
                  <p className="text-xs text-text-secondary mt-0.5">Choose to execute or skip this step.</p>
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => {
                        setMutationError(null);
                        resumeRun.mutate(
                          { runId: run.id },
                          { onError: handleMutationError('resume') }
                        );
                      }}
                      disabled={resumeRun.isPending}
                      className="px-3 py-1.5 text-xs font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      aria-label="Execute this step"
                    >
                      {resumeRun.isPending ? 'Executing...' : 'Execute Step'}
                    </button>
                    <button
                      onClick={() => {
                        setMutationError(null);
                        skipStep.mutate(actionable.step.id, { onError: handleMutationError('skip step') });
                      }}
                      disabled={skipStep.isPending}
                      className="px-3 py-1.5 text-xs font-medium text-text-primary bg-bg-elevated border border-border rounded-md hover:bg-bg-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      aria-label="Skip this step"
                    >
                      {skipStep.isPending ? 'Skipping...' : 'Skip Step'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Mutation error banner */}
          {mutationError && (
            <div className="mb-6 rounded-md bg-status-failed/10 border border-status-failed/30 p-4 flex items-center justify-between">
              <p className="text-sm text-status-failed">{mutationError}</p>
              <button
                onClick={() => setMutationError(null)}
                className="ml-4 text-status-failed hover:text-status-failed/80"
                aria-label="Dismiss error"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Dirty working tree banner */}
          {dirtyWorkingTree && (
            <div className="mb-6 rounded-md bg-yellow-50 border border-yellow-300 p-4">
              <div className="flex items-start gap-3">
                <svg className="h-5 w-5 text-yellow-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-yellow-800">
                    Cannot merge: the repo has {dirtyWorkingTree.dirty_files.length} uncommitted change{dirtyWorkingTree.dirty_files.length === 1 ? '' : 's'}
                  </p>
                  <p className="text-xs text-yellow-700 mt-1 font-mono truncate" title={dirtyWorkingTree.dirty_files.join(', ')}>
                    {dirtyWorkingTree.dirty_files.slice(0, 5).join(', ')}
                    {dirtyWorkingTree.dirty_files.length > 5 && ` and ${dirtyWorkingTree.dirty_files.length - 5} more`}
                  </p>
                  <p className="text-xs text-yellow-700 mt-2">
                    Commit or stash the changes in <span className="font-mono font-medium">{dirtyWorkingTree.branch}</span>, then try again.
                  </p>
                  <div className="flex items-center gap-2 mt-3">
                    <button
                      onClick={() => {
                        setDirtyWorkingTree(null);
                        mergeBack.mutate(
                          { runId: run.id, dirty_action: 'stash' },
                          {
                            onSuccess: (data) => setMergeResult(data.message),
                            onError: handleMutationError('merge back'),
                          },
                        );
                      }}
                      disabled={mergeBack.isPending}
                      className="px-3 py-1.5 text-xs font-medium text-yellow-800 bg-yellow-100 border border-yellow-300 rounded-md hover:bg-yellow-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {mergeBack.isPending ? 'Merging...' : 'Stash & Merge'}
                    </button>
                    <button
                      onClick={() => setDirtyWorkingTree(null)}
                      className="px-3 py-1.5 text-xs font-medium text-yellow-700 hover:text-yellow-800 transition-colors"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Merge success banner */}
          {mergeResult && (
            <div className="mb-6 rounded-md bg-status-completed/10 border border-status-completed/30 p-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <svg className="h-4 w-4 text-status-completed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                <p className="text-sm text-status-completed">{mergeResult}</p>
              </div>
              <button
                onClick={() => setMergeResult(null)}
                className="ml-4 text-status-completed hover:text-status-completed/80"
                aria-label="Dismiss"
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Pending actions banner */}
          {pendingActionsCount > 0 && (
            <div className="mb-4 rounded-md bg-bg-elevated border border-border px-3 py-2 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <svg className="h-4 w-4 text-text-secondary shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                <span className="text-sm font-medium text-text-primary whitespace-nowrap">
                  {pendingActionsCount} action{pendingActionsCount !== 1 ? 's' : ''} required
                </span>
              </div>
              {taskPendingActions.length > 0 && (
                <button
                  onClick={() => setSelectedPendingAction(primaryPendingAction)}
                  className="px-3 py-1.5 text-xs font-medium text-text-primary bg-bg-surface border border-border rounded-md hover:bg-bg-elevated hover:border-border-strong transition-colors shrink-0"
                >
                  {pendingClarificationAction ? 'Answer Questions →' : 'Review →'}
                </button>
              )}
            </div>
          )}

          {/* Stuck-run warning banner */}
          {isStuck && (
            <div className="mb-6 rounded-md bg-status-failed/10 border border-status-failed/30 px-4 py-3 flex items-start gap-3">
              <svg className="h-5 w-5 text-status-failed shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-status-failed">Run blocked</p>
                <p className="text-xs text-text-secondary mt-0.5">
                  Task <span className="font-medium">{stuckTaskName}</span> failed after exhausting all attempts. This run cannot make further progress.
                </p>
              </div>
            </div>
          )}

          {run.status === 'failed' && <RecoveryPanel run={run} /> /* FAILED runs only */}

          {['active', 'paused'].includes(run.status) && run.worktree_path && (
            <BranchStatusPanel runId={run.id} />
          )}

          {run.env_file_specs && run.env_file_specs.length > 0 && (
            <EnvFilesPanel runId={run.id} />
          )}

          {/* Agent error banner — shown when run paused/failed due to agent error */}
          {agentError && (
            <div className="mb-6 rounded-md bg-status-failed/10 border border-status-failed/30 px-4 py-3 flex items-start gap-3">
              <svg className="h-5 w-5 text-status-failed shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
              <div className="min-w-0">
                <p className="text-sm font-medium text-status-failed">
                  Agent error{agentError.taskTitle ? ` — ${agentError.taskTitle}` : ''}
                </p>
                <p className="text-xs text-text-secondary mt-0.5 font-mono break-all">
                  {agentError.errorMessage}
                </p>
              </div>
            </div>
          )}

          {/* Escalation banner — shown when run paused due to escalated requirement */}
          {run.status === 'paused' && run.pause_reason === 'requirement_escalated' && (
            <div className="mb-6 rounded-md bg-status-paused/10 border border-status-paused/30 px-4 py-3 flex items-start gap-3">
              <svg className="h-5 w-5 text-status-paused shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
              <div className="min-w-0">
                <p className="text-sm font-medium text-status-paused">
                  Agent escalated a requirement
                </p>
                <p className="text-xs text-text-secondary mt-0.5">
                  The agent flagged a requirement as unfulfillable. Review the escalated requirement below, then modify, skip, or resume the run.
                </p>
                {run.last_error && (
                  <p className="mt-1.5 text-xs text-text-secondary bg-bg-elevated rounded px-2 py-1 font-mono break-all">
                    {run.last_error}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Agent guidance panel for user_managed */}
          {activeTask && (
            <div className="mb-6">
              <AgentGuidancePanel run={run} />
            </div>
          )}

          {/* Per-model cost breakdown */}
          {((run.token_usage_by_model?.length ?? 0) > 0 ||
            run.total_tokens_read > 0 ||
            run.total_tokens_write > 0 ||
            run.estimated_cost_usd !== null) && (
            <div className="mb-6">
              <ModelCostBreakdown run={run} />
            </div>
          )}

          {/* View Changes */}
          <ReviewMergeTab runId={run.id} worktreePath={run.worktree_path ?? null} />
          </>
        </div>
      </div>

      <ResumeDialog
        open={showResumeDialog}
        run={run}
        onClose={() => setShowResumeDialog(false)}
      />


      {/* Clarification Modal */}
      {selectedPendingAction?.action_type === 'clarification' && selectedPendingAction.clarification_request && (
        <ClarificationModal
          open={true}
          onClose={() => setSelectedPendingAction(null)}
          clarificationRequest={selectedPendingAction.clarification_request}
          runId={runId}
          taskId={selectedPendingAction.task_id}
        />
      )}

      {/* Approval Modal */}
      {selectedPendingAction?.action_type === 'approval' && (
        <ApprovalModal
          open={true}
          onClose={() => setSelectedPendingAction(null)}
          pendingAction={selectedPendingAction}
          runId={runId}
          onReviewChanges={() => {
            setApprovalReviewAction(selectedPendingAction);
            setSelectedPendingAction(null);
          }}
        />
      )}

      {/* Full-screen approval review dialog */}
      {approvalReviewAction && (
        <ApprovalReviewDialog
          open={true}
          onClose={() => setApprovalReviewAction(null)}
          pendingAction={approvalReviewAction}
          runId={runId}
        />
      )}
    </div>
  );
}

export function RunDetail() {
  const { runId } = useParams<{ runId: string }>();

  return (
    <WebSocketProvider runId={runId}>
      <ReviewMergeProvider>
        <RunDetailInner runId={runId!} />
      </ReviewMergeProvider>
    </WebSocketProvider>
  );
}
