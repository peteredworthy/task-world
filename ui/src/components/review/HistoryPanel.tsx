import { useCommits } from '../../hooks/useReview';
import type { CommitEntry } from '../../types/review';

export type DiffScope = 'aggregate' | 'commit';

interface HistoryPanelProps {
  runId: string;
  scope: DiffScope;
  selectedCommitSha: string | null;
  onScopeChange: (scope: DiffScope) => void;
  onCommitSelect: (sha: string) => void;
}

type CommitBadge = 'prune' | 'agent' | 'back-merge';

function detectBadges(message: string): CommitBadge[] {
  const badges: CommitBadge[] = [];
  const lower = message.toLowerCase();

  if (lower.startsWith('prune:') || lower.includes('[prune]')) {
    badges.push('prune');
  }
  if (
    lower.startsWith('agent:') ||
    lower.includes('[agent]') ||
    lower.includes('agent fix') ||
    lower.includes('agent resolve')
  ) {
    badges.push('agent');
  }
  // Merge commits: "Merge branch", "Merge pull request", or back-merge patterns
  if (
    lower.startsWith('merge ') ||
    lower.includes('back-merge') ||
    lower.includes('back merge') ||
    lower.includes('[back-merge]')
  ) {
    badges.push('back-merge');
  }

  return badges;
}

function CommitBadge({ type }: { type: CommitBadge }) {
  const styles: Record<CommitBadge, string> = {
    prune: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    agent: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    'back-merge': 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  };
  const labels: Record<CommitBadge, string> = {
    prune: 'prune',
    agent: 'agent',
    'back-merge': 'back-merge',
  };

  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${styles[type]}`}
    >
      {labels[type]}
    </span>
  );
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}

function CommitRow({
  commit,
  isSelected,
  onClick,
}: {
  commit: CommitEntry;
  isSelected: boolean;
  onClick: () => void;
}) {
  const badges = detectBadges(commit.message);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded px-2 py-2 text-left transition-colors ${
        isSelected
          ? 'bg-blue-500/15 border border-blue-500/30'
          : 'hover:bg-bg-muted border border-transparent'
      }`}
    >
      {/* Top row: SHA + badges */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <code
          className={`font-mono text-[11px] font-semibold ${
            isSelected ? 'text-blue-400' : 'text-text-muted'
          }`}
        >
          {commit.short_sha}
        </code>
        {badges.map((badge) => (
          <CommitBadge key={badge} type={badge} />
        ))}
      </div>

      {/* Message */}
      <p
        className={`mt-0.5 truncate text-xs ${
          isSelected ? 'text-text-primary' : 'text-text-secondary'
        }`}
        title={commit.message}
      >
        {commit.message}
      </p>

      {/* Bottom row: author + timestamp */}
      <div className="mt-1 flex items-center gap-2 text-[10px] text-text-muted">
        <span className="truncate">{commit.author}</span>
        <span className="shrink-0">{formatTimestamp(commit.timestamp)}</span>
      </div>
    </button>
  );
}

export function HistoryPanel({
  runId,
  scope,
  selectedCommitSha,
  onScopeChange,
  onCommitSelect,
}: HistoryPanelProps) {
  const { data: commits, isLoading, isError } = useCommits(runId);

  const handleCommitClick = (sha: string) => {
    onCommitSelect(sha);
    onScopeChange('commit');
  };

  return (
    <div className="rounded-md border border-border bg-bg-elevated p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
        Branch History
        {commits && commits.length > 0 && (
          <span className="ml-1.5 font-normal text-text-muted">({commits.length})</span>
        )}
      </h3>

      {/* Scope radio toggle */}
      <div className="mt-3 flex items-center gap-1 rounded border border-border bg-bg-muted p-0.5">
        <button
          type="button"
          onClick={() => onScopeChange('aggregate')}
          className={`flex-1 rounded px-2 py-1 text-[11px] transition-colors ${
            scope === 'aggregate'
              ? 'bg-bg-elevated text-text-primary shadow-sm'
              : 'text-text-muted hover:text-text-secondary'
          }`}
        >
          Overall
        </button>
        <button
          type="button"
          onClick={() => {
            onScopeChange('commit');
          }}
          className={`flex-1 rounded px-2 py-1 text-[11px] transition-colors ${
            scope === 'commit'
              ? 'bg-bg-elevated text-text-primary shadow-sm'
              : 'text-text-muted hover:text-text-secondary'
          }`}
        >
          Selected Commit
        </button>
      </div>

      {/* Commit list */}
      <div className="mt-3">
        {isLoading ? (
          <div className="flex flex-col gap-2" aria-label="Loading branch history">
            {[1, 2, 3].map((i) => (
              <div key={i} className="rounded border border-transparent px-2 py-2">
                <div className="flex items-center gap-1.5">
                  <span className="skeleton h-3 w-12" />
                </div>
                <span className="skeleton mt-1.5 block h-3 w-full" />
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="skeleton h-2.5 w-20" />
                  <span className="skeleton h-2.5 w-16" />
                </div>
              </div>
            ))}
          </div>
        ) : isError ? (
          <p className="text-xs text-status-failed">Failed to load commits.</p>
        ) : !commits || commits.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-text-muted opacity-50"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="4" />
              <line x1="1.05" y1="12" x2="7" y2="12" />
              <line x1="17.01" y1="12" x2="22.96" y2="12" />
            </svg>
            <p className="text-xs text-text-muted">No commits on this branch</p>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {commits.map((commit) => (
              <CommitRow
                key={commit.sha}
                commit={commit}
                isSelected={selectedCommitSha === commit.sha}
                onClick={() => handleCommitClick(commit.sha)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
