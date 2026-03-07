import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useRuns, useRoutines, useStartRun, usePauseRun, useCancelRun, useDeleteRun, useGlobalConfig } from '../hooks/useApi';
import { RunCard } from '../components/dashboard/RunCard';
import { RunFilters } from '../components/dashboard/RunFilters';
import { recencyToMs } from '../lib/recency';
import { CreateRunModal } from '../components/dashboard/CreateRunModal';
import { ResumeDialog } from '../components/run/ResumeDialog';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ApiError } from '../api/client';
import { useCreateRunModal } from '../hooks/useCreateRunModal';
import { InspectorPanel } from '../components/detail/InspectorPanel';
import type { TaskSummary, RunResponse } from '../types';

export function Dashboard() {
  const maxRecentRuns = useGlobalConfig().data?.dashboard_max_recent_runs ?? 50;
  const [statusFilter, setStatusFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [recencyFilter, setRecencyFilter] = useState('');
  const createRunModal = useCreateRunModal();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const searchQuery = searchParams.get('search') ?? '';
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [resumeTarget, setResumeTarget] = useState<RunResponse | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [inspectorTarget, setInspectorTarget] = useState<{
    runId: string;
    task: TaskSummary;
  } | null>(null);

  // Handle routine query parameter for auto-opening create modal
  useEffect(() => {
    const routineParam = searchParams.get('routine');
    if (routineParam) {
      createRunModal.open(routineParam);
      // Clear the query parameter to avoid re-triggering on navigation
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete('routine');
        return next;
      }, { replace: true });
    }
  }, [searchParams, createRunModal, setSearchParams]);

  function handleTaskClick(runId: string, task: TaskSummary) {
    if (inspectorTarget?.task.id === task.id) {
      setInspectorTarget(null); // toggle off
    } else {
      setInspectorTarget({ runId, task });
    }
  }

  const handleRecencyChange = useCallback((value: string) => {
    setRecencyFilter(value);
  }, []);

  const handleToggle = useCallback((runId: string) => {
    setExpandedRunId(prev => (prev === runId ? null : runId));
  }, []);

  useEffect(() => {
    if (!mutationError) return;
    const timer = setTimeout(() => setMutationError(null), 5000);
    return () => clearTimeout(timer);
  }, [mutationError]);

  const runsParams = useMemo(
    () => statusFilter ? { status: statusFilter, limit: maxRecentRuns } : { limit: maxRecentRuns },
    [statusFilter, maxRecentRuns],
  );
  const { data, isLoading, isPlaceholderData, error, dataUpdatedAt } = useRuns(runsParams);
  const { data: routinesData } = useRoutines();
  const routineNames = new Map(routinesData?.routines?.map(r => [r.id, r.name]) ?? []);
  const startRun = useStartRun();
  const pauseRun = usePauseRun();
  const cancelRun = useCancelRun();
  const deleteRun = useDeleteRun();

  const handleMutationError = useCallback((action: string) => (err: Error) => {
    const detail = err instanceof ApiError
      ? err.message
      : 'Something went wrong';
    setMutationError(`Failed to ${action} run: ${detail}`);
  }, []);

  const runs = useMemo(() => {
    let filtered = data?.runs ?? [];

    // Handle "needs_input" filter by checking for pending actions
    if (statusFilter === 'needs_input') {
      filtered = filtered.filter(r =>
        r.steps.some(step =>
          step.tasks.some(task => task.pending_action_type !== null) ||
          (step.has_approval_gate && step.approval_status === 'pending')
        ),
      );
    }

    // Client-side repo filter
    if (projectFilter) {
      const lower = projectFilter.toLowerCase();
      filtered = filtered.filter(r => r.repo_name.toLowerCase().includes(lower));
    }

    // Client-side recency filter: use dataUpdatedAt as fresh timestamp
    // so cutoff refreshes on each data refetch instead of drifting
    const ms = recencyToMs(recencyFilter);
    if (ms !== null) {
      const cutoff = dataUpdatedAt - ms;
      filtered = filtered.filter(r => new Date(r.updated_at).getTime() >= cutoff);
    }

    // Client-side text search filter (from URL ?search=)
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(r =>
        r.id.toLowerCase().includes(q) ||
        r.repo_name.toLowerCase().includes(q) ||
        (r.routine_id ?? '').toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [data, projectFilter, recencyFilter, dataUpdatedAt, searchQuery, statusFilter]);

  const activeCount = runs.filter(r => r.status === 'active').length;
  const totalCount = runs.length;

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <h1 className="text-2xl font-bold text-text-primary">Runs</h1>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Search runs..."
                value={searchQuery}
                onChange={e => {
                  const value = e.target.value;
                  if (value) {
                    navigate('/?search=' + encodeURIComponent(value), { replace: true });
                  } else {
                    navigate('/', { replace: true });
                  }
                }}
                className="rounded-md border border-border bg-bg-card px-3 py-1.5 text-sm text-text-primary shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none hover:border-border-hover transition-colors w-full sm:w-48"
              />
              <span className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted text-[10px] bg-bg-hover px-1 py-0.5 rounded pointer-events-none">
                &#x2318;K
              </span>
            </div>
            <RunFilters
              statusFilter={statusFilter}
              onStatusChange={setStatusFilter}
              projectFilter={projectFilter}
              onProjectChange={setProjectFilter}
              recencyFilter={recencyFilter}
              onRecencyChange={handleRecencyChange}
              activeCount={activeCount}
              totalCount={totalCount}
            />
            <button
              onClick={() => createRunModal.open()}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 shadow-md transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Run
            </button>
          </div>
        </div>

        {isLoading && !isPlaceholderData && (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        )}

        {error && (
          <div className="rounded-md bg-status-failed/10 border border-status-failed/30 p-4">
            <p className="text-sm text-status-failed">
              {error instanceof ApiError
                ? error.message
                : 'Failed to load runs. Is the backend running?'}
            </p>
          </div>
        )}

        {mutationError && (
          <div className="rounded-md bg-status-failed/10 border border-status-failed/30 p-4 mb-4 flex items-center justify-between">
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

        {!isLoading && !isPlaceholderData && !error && runs.length === 0 && (
          <EmptyState message="No runs found. Create one to get started." />
        )}

        <div className="space-y-2">
          {runs.map(run => (
            <RunCard
              key={run.id}
              run={run}
              routineName={routineNames.get(run.routine_id ?? '') ?? run.routine_id ?? 'Unknown routine'}
              expanded={expandedRunId === run.id}
              onToggle={() => handleToggle(run.id)}
              onStart={id => { setMutationError(null); startRun.mutate(id, { onError: handleMutationError('start') }); }}
              onPause={id => { setMutationError(null); pauseRun.mutate(id, { onError: handleMutationError('pause') }); }}
              onResume={() => setResumeTarget(run)}
              onCancel={id => { setMutationError(null); cancelRun.mutate(id, { onError: handleMutationError('cancel') }); }}
              onDelete={id => setDeleteTarget(id)}
              onTaskClick={handleTaskClick}
              loading={{
                start: startRun.isPending && startRun.variables === run.id,
                pause: pauseRun.isPending && pauseRun.variables === run.id,
                cancel: cancelRun.isPending && cancelRun.variables === run.id,
                delete: deleteRun.isPending && deleteRun.variables === run.id,
              }}
            />
          ))}
        </div>

        <CreateRunModal open={createRunModal.isOpen} onClose={createRunModal.close} />

        <ResumeDialog
          open={!!resumeTarget}
          run={resumeTarget}
          onClose={() => setResumeTarget(null)}
        />

        <ConfirmDialog
          open={!!deleteTarget}
          title="Delete Run"
          message="Are you sure? This action cannot be undone."
          confirmLabel="Delete"
          onConfirm={() => {
            if (deleteTarget) {
              setMutationError(null);
              deleteRun.mutate(deleteTarget, { onError: handleMutationError('delete') });
              setDeleteTarget(null);
            }
          }}
          onCancel={() => setDeleteTarget(null)}
        />
      </div>
      {inspectorTarget && (
        <InspectorPanel
          task={inspectorTarget.task}
          runId={inspectorTarget.runId}
          onClose={() => setInspectorTarget(null)}
        />
      )}
    </div>
  );
}
