import { useRef, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useRepos, useRepoBranches, useRepoStats } from '../hooks/useApi';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ApiError, api } from '../api/client';
import { useCreateRunModal } from '../hooks/useCreateRunModal';
import { CreateRunModal } from '../components/dashboard/CreateRunModal';
import { useFocusTrap } from '../hooks/useFocusTrap';
import type { RepoResponse } from '../types/repos';

const MAX_BRANCHES_SHOWN = 5;

// --- Add Repo Modal ---

interface AddRepoModalProps {
  open: boolean;
  onClose: () => void;
}

type AddTab = 'url' | 'path';

function AddRepoModal({ open, onClose }: AddRepoModalProps) {
  const qc = useQueryClient();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [tab, setTab] = useState<AddTab>('url');
  const [value, setValue] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setValue('');
    setError(null);
    setTab('url');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const titleId = 'add-repo-modal-title';
  const placeholder = tab === 'url'
    ? 'https://github.com/org/repo.git'
    : '/absolute/path/to/repo';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await api.addRepo(tab === 'url' ? { url: value.trim() } : { path: value.trim() });
      await qc.invalidateQueries({ queryKey: ['repos'] });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add repository');
    } finally {
      setIsSubmitting(false);
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
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[480px] mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-border">
          <h2 id={titleId} className="text-lg font-semibold text-text-primary">
            Add Repository
          </h2>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border">
          <button
            type="button"
            onClick={() => { setTab('url'); setError(null); setValue(''); }}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
              tab === 'url'
                ? 'text-accent-purple border-b-2 border-accent-purple'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            By URL
          </button>
          <button
            type="button"
            onClick={() => { setTab('path'); setError(null); setValue(''); }}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
              tab === 'path'
                ? 'text-accent-purple border-b-2 border-accent-purple'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            By Path
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1.5">
              {tab === 'url' ? 'Git clone URL' : 'Filesystem path'}
            </label>
            <input
              type="text"
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={placeholder}
              autoFocus
              className="w-full bg-bg-elevated border border-border rounded-md px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:ring-2 focus:ring-accent-purple/50 focus:border-accent-purple"
            />
          </div>

          {error && (
            <p className="text-sm text-status-failed">{error}</p>
          )}

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-text-secondary bg-bg-elevated rounded-md hover:bg-bg-hover transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !value.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
            >
              {isSubmitting && <Spinner className="h-3.5 w-3.5" />}
              {tab === 'url' ? 'Clone' : 'Add'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- Expanded card section (branches + run count) ---

function RepoCardExpanded({ repo }: { repo: RepoResponse }) {
  const branchesQuery = useRepoBranches(repo.name, { include_remote: false });
  const statsQuery = useRepoStats(repo.name);

  return (
    <div className="mt-3 pt-3 border-t border-border-subtle space-y-3">
      {/* Run count */}
      <div className="flex items-center gap-2 text-sm">
        <svg className="h-4 w-4 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {statsQuery.isLoading && <span className="text-text-muted">Loading...</span>}
        {statsQuery.data !== undefined && (
          <Link
            to={`/?repo=${encodeURIComponent(repo.name)}`}
            className="text-accent-purple hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {statsQuery.data.run_count} {statsQuery.data.run_count === 1 ? 'run' : 'runs'}
          </Link>
        )}
        {statsQuery.error && <span className="text-text-muted">—</span>}
      </div>

      {/* Recent branches */}
      <div>
        <div className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1.5">
          Recent branches
        </div>
        {branchesQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <Spinner />
            <span>Loading branches...</span>
          </div>
        )}
        {branchesQuery.error && (
          <p className="text-sm text-text-muted">Failed to load branches.</p>
        )}
        {branchesQuery.data && (
          <>
            <ul className="space-y-0.5">
              {branchesQuery.data.branches.slice(0, MAX_BRANCHES_SHOWN).map((branch) => (
                <li key={branch.name} className="flex items-center gap-2 text-sm">
                  <span className="font-mono text-xs text-text-muted w-16 shrink-0 truncate" title={branch.commit}>
                    {branch.commit.slice(0, 7)}
                  </span>
                  <span className="font-mono text-text-primary truncate" title={branch.name}>
                    {branch.name}
                  </span>
                </li>
              ))}
            </ul>
            {branchesQuery.data.total > MAX_BRANCHES_SHOWN && (
              <p className="text-xs text-text-muted mt-1">
                &hellip; and {branchesQuery.data.total - MAX_BRANCHES_SHOWN} more
              </p>
            )}
            {branchesQuery.data.branches.length === 0 && (
              <p className="text-sm text-text-muted">No local branches found.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// --- Repo Card ---

function RepoCard({
  repo,
  onCreateRun,
  onRemove,
}: {
  repo: RepoResponse;
  onCreateRun: () => void;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-bg-secondary rounded-lg border border-border-subtle hover:border-accent-purple/50 transition-colors">
      <div
        className="p-4 cursor-pointer select-none"
        onClick={() => setExpanded((prev) => !prev)}
        role="button"
        aria-expanded={expanded}
      >
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold text-text-primary truncate">
                {repo.name}
              </h3>
              {/* Chevron indicator */}
              <svg
                className={`h-4 w-4 text-text-muted shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
            <div className="flex items-center gap-4 mt-2 text-sm text-text-muted">
              <div className="flex items-center gap-1.5">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="truncate" title={repo.path}>{repo.path}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                </svg>
                <span className="font-mono text-xs">{repo.default_branch}</span>
              </div>
            </div>
          </div>
          <div className="ml-4 flex items-center gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onCreateRun();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 shadow-sm transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Create Run
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRemove();
              }}
              aria-label={`Remove ${repo.name}`}
              className="inline-flex items-center justify-center h-8 w-8 rounded-md text-text-muted hover:text-status-failed hover:bg-status-failed/10 transition-colors"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>

        {expanded && <RepoCardExpanded repo={repo} />}
      </div>
    </div>
  );
}

// --- Repos Page ---

export function Repos() {
  const { data, isLoading, error } = useRepos();
  const qc = useQueryClient();
  const createRunModal = useCreateRunModal();
  const navigate = useNavigate();

  const [addModalOpen, setAddModalOpen] = useState(false);
  const [repoToRemove, setRepoToRemove] = useState<string | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  function handleCreateRun(repoName: string) {
    createRunModal.open();
    // Navigate to dashboard with repo pre-selected
    navigate(`/?repo=${encodeURIComponent(repoName)}`);
  }

  async function handleConfirmRemove() {
    if (!repoToRemove) return;
    setIsRemoving(true);
    try {
      await api.removeRepo(repoToRemove);
      await qc.invalidateQueries({ queryKey: ['repos'] });
    } finally {
      setIsRemoving(false);
      setRepoToRemove(null);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-bold text-text-primary">Repositories</h1>
        <button
          onClick={() => setAddModalOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 shadow-sm transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Repository
        </button>
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      )}

      {error && (
        <div className="rounded-md bg-status-failed/10 border border-status-failed/30 p-4">
          <p className="text-sm text-status-failed">
            {error instanceof ApiError
              ? error.message
              : 'Failed to load repositories. Is the backend running?'}
          </p>
        </div>
      )}

      {!isLoading && !error && (!data?.repos || data.repos.length === 0) && (
        <EmptyState
          message="No repositories configured. Add one with the button above."
          variant="generic"
        />
      )}

      {!isLoading && !error && data?.repos && data.repos.length > 0 && (
        <div className="space-y-3">
          {data.repos.map(repo => (
            <RepoCard
              key={repo.name}
              repo={repo}
              onCreateRun={() => handleCreateRun(repo.name)}
              onRemove={() => setRepoToRemove(repo.name)}
            />
          ))}
        </div>
      )}

      <CreateRunModal open={createRunModal.isOpen} onClose={createRunModal.close} />

      <AddRepoModal open={addModalOpen} onClose={() => setAddModalOpen(false)} />

      <ConfirmDialog
        open={repoToRemove !== null}
        title="Remove Repository"
        message={`Remove "${repoToRemove}" from the repositories list? Cloned repositories will be deleted from disk; symlinked repositories will only have the symlink removed.`}
        confirmLabel={isRemoving ? 'Removing...' : 'Remove'}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRepoToRemove(null)}
      />
    </div>
  );
}
