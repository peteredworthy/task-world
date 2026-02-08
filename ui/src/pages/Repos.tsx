import { useNavigate } from 'react-router-dom';
import { useRepos } from '../hooks/useApi';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';
import { ApiError } from '../api/client';
import { useCreateRunModal } from '../hooks/useCreateRunModal';
import { CreateRunModal } from '../components/dashboard/CreateRunModal';
import type { RepoResponse } from '../types/repos';

function RepoCard({ repo, onCreateRun }: { repo: RepoResponse; onCreateRun: () => void }) {
  return (
    <div className="bg-bg-secondary rounded-lg border border-border-subtle p-4 hover:border-accent-purple/50 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="text-lg font-semibold text-text-primary truncate">
            {repo.name}
          </h3>
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
        <button
          onClick={onCreateRun}
          className="ml-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 shadow-sm transition-colors"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Create Run
        </button>
      </div>
    </div>
  );
}

export function Repos() {
  const { data, isLoading, error } = useRepos();
  const createRunModal = useCreateRunModal();
  const navigate = useNavigate();

  function handleCreateRun(repoName: string) {
    createRunModal.open();
    // Navigate to dashboard with repo pre-selected
    navigate(`/?repo=${encodeURIComponent(repoName)}`);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-bold text-text-primary">Repositories</h1>
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
          message="No repositories configured. Add repositories via CLI or configuration file."
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
            />
          ))}
        </div>
      )}

      <CreateRunModal open={createRunModal.isOpen} onClose={createRunModal.close} />
    </div>
  );
}
