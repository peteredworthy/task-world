import { useState, useCallback, useEffect, useMemo } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { useRun, useRoutine, usePauseRun, useCancelRun, useMergeBack } from '../hooks/useApi';
import { useActivityStream } from '../hooks/useActivityStream';
import { usePendingActions } from '../hooks/usePendingActions';
import { WebSocketProvider } from '../context/WebSocketContext';
import { useWebSocketStatus } from '../hooks/useWebSocketStatus';
import { RunStatusBadge } from '../components/StatusBadge';
import { ConnectionIndicator } from '../components/ConnectionIndicator';
import { AgentGuidancePanel } from '../components/guidance/AgentGuidancePanel';
import { ResumeDialog } from '../components/run/ResumeDialog';
import { ClarificationModal } from '../components/detail/ClarificationModal';
import { ApprovalModal } from '../components/detail/ApprovalModal';
import { Spinner } from '../components/Spinner';
import { MetricsBar } from '../components/detail/MetricsBar';
import { ActivityFeed } from '../components/detail/ActivityFeed';
import { UpcomingPlan } from '../components/detail/UpcomingPlan';
import { RecoveryPanel } from '../components/detail/RecoveryPanel';
import { StepApprovalBanner } from '../components/detail/StepApprovalBanner';
import { BranchStatusPanel } from '../components/detail/BranchStatusPanel';
import { EnvFilesPanel } from '../components/detail/EnvFilesPanel';
import { classifyTasks, getLastAgentError } from '../lib/activity';
import { formatRelativeTime } from '../lib/format';
import { AgentIcon } from '../components/AgentIcon';
import { ApiError } from '../api/client';
import type { RunResponse } from '../types';
import type { StepSummarySchema } from '../types/routines';
import type { PendingAction } from '../types/clarifications';

/** Compact horizontal progress bar showing step completion at a glance. Blocks scroll to step. */
function StepProgressBar({
  run,
  routineSteps,
}: {
  run: RunResponse;
  routineSteps: StepSummarySchema[] | undefined;
}) {
  const isTerminal = run.status === 'completed' || run.status === 'failed';

  const scrollToStep = (stepId: string) => {
    const el = document.getElementById(`step-${stepId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="flex items-center gap-1" role="progressbar" aria-label="Step progress">
      {run.steps.map((step, i) => {
        const isCurrent = i === run.current_step_index;
        const completed = step.completed;
        const isFuture = i > run.current_step_index && !completed;
        const hasFailed = step.tasks.some(t => t.status === 'failed');
        const stepTitle = step.title || routineSteps?.[i]?.title || step.config_id;
        const doneCount = step.tasks.filter(t => t.status === 'completed').length;
        const totalCount = step.tasks.length;

        let bgClass = 'bg-border';
        if (hasFailed) bgClass = 'bg-status-failed';
        else if (completed) bgClass = 'bg-status-completed';
        else if (isCurrent) bgClass = 'bg-accent-purple';

        // Only pulse the current step when the run is actively running
        const shouldPulse = isCurrent && !hasFailed && !isTerminal;

        return (
          <button
            key={step.id}
            className="flex-1 group relative cursor-pointer"
            title={`${stepTitle} (${doneCount}/${totalCount})`}
            onClick={() => scrollToStep(step.id)}
            aria-label={`Jump to step ${i + 1}: ${stepTitle}`}
          >
            <div
              className={
                'h-2 rounded-full transition-colors ' +
                bgClass +
                (isFuture ? ' opacity-30' : '') +
                (shouldPulse ? ' animate-pulse-dot' : '')
              }
            />
            {/* Tooltip on hover */}
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 bg-bg-elevated border border-border rounded text-[10px] text-text-secondary whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10">
              S{i + 1}: {stepTitle} ({doneCount}/{totalCount})
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** Detect if the run is stuck: active but a task has failed with no remaining attempts. */
function isRunStuck(run: RunResponse): { stuck: boolean; failedTask: string | null } {
  if (run.status !== 'active') return { stuck: false, failedTask: null };
  for (const step of run.steps) {
    const failed = step.tasks.find(
      t => t.status === 'failed' && t.current_attempt >= t.max_attempts,
    );
    if (failed) {
      return { stuck: true, failedTask: failed.title || failed.config_id };
    }
  }
  return { stuck: false, failedTask: null };
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
  const [showResumeDialog, setShowResumeDialog] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mergeResult, setMergeResult] = useState<string | null>(null);
  const [dirtyWorkingTree, setDirtyWorkingTree] = useState<{ branch: string; dirty_files: string[] } | null>(null);
  const [selectedPendingAction, setSelectedPendingAction] = useState<PendingAction | null>(null);

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
  const routineSteps: StepSummarySchema[] | undefined = routine?.steps;
  const events = activityData?.events ?? [];

  // Classify tasks into active (have events or non-pending status) vs upcoming
  const { active: activeTasks, upcoming } = classifyTasks(run, events);

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
              <div className="flex items-center gap-3 mt-1.5">
                <span className="inline-flex items-center rounded bg-bg-elevated px-2 py-0.5 text-[11px] font-mono text-text-muted">
                  {run.id.slice(0, 8)}
                </span>
                {run.started_at && (
                  <span className="text-xs text-text-muted">
                    Started {formatRelativeTime(run.started_at)}
                  </span>
                )}
                {!run.started_at && (
                  <span className="text-xs text-text-muted">
                    Created {formatRelativeTime(run.created_at)}
                  </span>
                )}
              </div>
              {run.agent_type && (
                <div className="flex items-center gap-2 mt-1.5 text-xs text-text-secondary">
                  <span className="text-text-muted">Agent:</span>
                  <div className="flex items-center gap-1.5">
                    <AgentIcon icon={run.agent_icon} className="h-3.5 w-3.5" />
                    <span className="font-medium">{run.agent_type_display}</span>
                    {'model' in run.agent_config && typeof run.agent_config.model === 'string' && (
                      <>
                        <span className="text-text-muted">·</span>
                        <span className="text-text-muted">
                          Model: {run.agent_config.model as string}
                        </span>
                      </>
                    )}
                  </div>
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
              {run.status === 'completed' && !mergeResult && (
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
              )}
            </div>
          </div>

          {/* Metrics Bar */}
          <div className="mt-4 mb-6">
            <MetricsBar run={run} />
          </div>

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

          {/* Agent guidance panel for user_managed */}
          {activeTask && (
            <div className="mb-6">
              <AgentGuidancePanel run={run} />
            </div>
          )}

          {/* Step progress bar */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wide">
                Progress
              </h2>
              <span className="text-[11px] text-text-muted">
                {run.status === 'completed'
                  ? `All ${run.steps.length} steps done`
                  : run.status === 'failed'
                    ? `Failed at step ${run.current_step_index + 1} of ${run.steps.length}`
                    : `Step ${run.current_step_index + 1} of ${run.steps.length}`}
              </span>
            </div>
            <StepProgressBar run={run} routineSteps={routineSteps} />
          </div>

          {/* Per-step approval gates */}
          <div className="mb-2">
            {run.steps.map((step, index) => (
              <div key={step.id} id={`step-${step.id}`}>
                <StepApprovalBanner runId={run.id} step={step} isCurrentStep={index === run.current_step_index} />
              </div>
            ))}
          </div>

          {/* Activity Feed */}
          <div className="mb-6">
            <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide mb-3">
              Activity
            </h2>
            <ActivityFeed
              events={events}
              activeTasks={activeTasks}
              run={run}
            />
          </div>

          {/* Upcoming Plan */}
          {upcoming.length > 0 && (
            <div className="mb-6">
              <UpcomingPlan
                tasks={upcoming}
              />
            </div>
          )}
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
        />
      )}
    </div>
  );
}

export function RunDetail() {
  const { runId } = useParams<{ runId: string }>();

  return (
    <WebSocketProvider runId={runId}>
      <RunDetailInner runId={runId!} />
    </WebSocketProvider>
  );
}
