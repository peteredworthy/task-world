interface RunFiltersProps {
  statusFilter: string;
  onStatusChange: (status: string) => void;
  projectFilter: string;
  onProjectChange: (project: string) => void;
  recencyFilter: string;
  onRecencyChange: (recency: string) => void;
  activeCount: number;
  totalCount: number;
}

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'needs_input', label: 'Needs Input' },
];

const RECENCY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All time' },
  { value: '1h', label: 'Last hour' },
  { value: '4h', label: 'Last 4 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '1w', label: 'Last week' },
];

const selectClasses =
  'min-w-0 rounded-md border border-border bg-bg-card px-3 py-1.5 text-sm text-text-primary shadow-sm ' +
  'focus:border-accent-purple focus:outline-none hover:border-border-hover transition-colors';

export function RunFilters({
  statusFilter,
  onStatusChange,
  projectFilter,
  onProjectChange,
  recencyFilter,
  onRecencyChange,
  activeCount,
  totalCount,
}: RunFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <select
        value={statusFilter}
        onChange={e => onStatusChange(e.target.value)}
        className={selectClasses}
        aria-label="Filter by status"
      >
        {STATUS_OPTIONS.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <select
        value={recencyFilter}
        onChange={e => onRecencyChange(e.target.value)}
        className={selectClasses}
        aria-label="Filter by recency"
      >
        {RECENCY_OPTIONS.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <input
        type="text"
        placeholder="Filter by project..."
        value={projectFilter}
        onChange={e => onProjectChange(e.target.value)}
        aria-label="Filter by project"
        className={
          'rounded-md border border-border bg-bg-card px-3 py-1.5 text-sm text-text-primary shadow-sm ' +
          'placeholder:text-text-muted focus:border-accent-purple focus:outline-none ' +
          'hover:border-border-hover transition-colors w-full sm:w-48'
        }
      />
      <div
        className="flex items-center gap-1.5 rounded-md border border-border bg-bg-elevated px-2.5 py-1.5 text-xs font-mono text-text-secondary"
        role="status"
        aria-label={`Running ${activeCount} of ${totalCount} runs`}
      >
        <span className="text-status-active font-semibold">Running: {activeCount}</span>
        <span className="text-text-muted">/</span>
        <span>Total: {totalCount}</span>
      </div>
    </div>
  );
}
