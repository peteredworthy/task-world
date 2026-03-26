import { useState, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useRoutines, useArchiveRoutine, useUnarchiveRoutine } from '../hooks/useApi';
import { Spinner } from '../components/Spinner';
import { EmptyState } from '../components/EmptyState';
import { RoutineCard } from '../components/routines/RoutineCard';
import type { RoutineSummary } from '../types/routines';

type SourceFilter = 'all' | 'local' | 'project' | 'external';

const SOURCE_FILTERS: { key: SourceFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'local', label: 'Local' },
  { key: 'project', label: 'Project' },
  { key: 'external', label: 'External' },
];

const SOURCE_SECTION_META: Record<string, { label: string }> = {
  local: { label: 'Local Routines' },
  project: { label: 'Project Routines' },
  external: { label: 'External Routines' },
};

/** Order sources appear in the grouped view. */
const SOURCE_ORDER = ['local', 'project', 'external'];

export function RoutineLibrary() {
  const [showArchived, setShowArchived] = useState(false);
  const { data, isLoading, error } = useRoutines({ includeArchived: showArchived });
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const archiveMutation = useArchiveRoutine();
  const unarchiveMutation = useUnarchiveRoutine();

  const routines = useMemo(() => data?.routines ?? [], [data]);

  // Filter by search and source (archived routines already filtered by API unless showArchived)
  const filtered = useMemo(() => {
    let result = routines;

    if (sourceFilter !== 'all') {
      result = result.filter((r) => r.source === sourceFilter);
    }

    if (search.trim()) {
      const lower = search.toLowerCase();
      result = result.filter(
        (r) =>
          r.name.toLowerCase().includes(lower) ||
          (r.description ?? '').toLowerCase().includes(lower)
      );
    }

    return result;
  }, [routines, sourceFilter, search]);

  // Group by source for sectioned display
  const grouped = useMemo(() => {
    const groups = new Map<string, RoutineSummary[]>();
    for (const routine of filtered) {
      const key = routine.source;
      const existing = groups.get(key);
      if (existing) {
        existing.push(routine);
      } else {
        groups.set(key, [routine]);
      }
    }
    return groups;
  }, [filtered]);

  // Sorted source keys
  const sortedSources = useMemo(() => {
    return SOURCE_ORDER.filter((s) => grouped.has(s));
  }, [grouped]);

  function handleSelect(routine: RoutineSummary) {
    navigate('/?routine=' + encodeURIComponent(routine.id));
  }

  function handleArchive(routine: RoutineSummary) {
    archiveMutation.mutate(routine.id);
  }

  function handleUnarchive(routine: RoutineSummary) {
    unarchiveMutation.mutate(routine.id);
  }

  // Count per source (from full list returned by API)
  const sourceCounts = useMemo(() => {
    const counts: Record<string, number> = { all: routines.length };
    for (const r of routines) {
      counts[r.source] = (counts[r.source] ?? 0) + 1;
    }
    return counts;
  }, [routines]);

  return (
    <div className="p-6 max-w-[1200px]">
      {/* Breadcrumb */}
      <nav className="mb-2 text-text-muted text-xs" aria-label="Breadcrumb">
        <ol className="flex items-center gap-1">
          <li>
            <Link
              to="/"
              className="hover:text-text-secondary transition-colors"
            >
              Home
            </Link>
          </li>
          <li aria-hidden="true">/</li>
          <li className="text-text-secondary" aria-current="page">
            Routine Library
          </li>
        </ol>
      </nav>

      {/* Title row */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-text-primary">
          Routine Library
        </h1>
        <p className="text-text-secondary text-sm mt-1">
          Browse and manage your automation workflow templates. Select a
          routine to create a new run.
        </p>
      </div>

      {/* Search bar */}
      <div className="relative mb-4">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted pointer-events-none"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          placeholder="Search routines by name or description..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-bg-card border border-border rounded-md pl-10 pr-4 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-purple/50 focus:ring-1 focus:ring-accent-purple/30 transition-colors"
          aria-label="Search routines"
        />
      </div>

      {/* Filter tabs + archived toggle */}
      <div className="flex items-center justify-between mb-6">
        <div
          className="flex items-center gap-1"
          role="tablist"
          aria-label="Filter routines by source"
        >
          {SOURCE_FILTERS.map(({ key, label }) => {
            const isActive = sourceFilter === key;
            const count = sourceCounts[key] ?? 0;
            return (
              <button
                key={key}
                role="tab"
                aria-selected={isActive}
                onClick={() => setSourceFilter(key)}
                className={
                  'px-3 py-1.5 rounded-md text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-accent-purple/40 ' +
                  (isActive
                    ? 'bg-accent-purple/20 text-text-primary'
                    : 'text-text-muted hover:text-text-secondary hover:bg-bg-hover')
                }
              >
                {label}
                {count > 0 && (
                  <span
                    className={
                      'ml-1.5 inline-flex items-center justify-center min-w-[18px] h-[18px] rounded-full px-1 text-[10px] font-semibold ' +
                      (isActive
                        ? 'bg-accent-purple/30 text-accent-purple'
                        : 'bg-bg-elevated text-text-muted')
                    }
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Show archived toggle */}
        <button
          onClick={() => setShowArchived((v) => !v)}
          className={
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-accent-purple/40 ' +
            (showArchived
              ? 'bg-accent-purple/20 text-text-primary'
              : 'text-text-muted hover:text-text-secondary hover:bg-bg-hover')
          }
          aria-pressed={showArchived}
        >
          <svg
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
          </svg>
          {showArchived ? 'Hide Archived' : 'Show Archived'}
        </button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex justify-center py-16">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="rounded-md bg-red-900/20 border border-red-800/50 p-4 mb-6">
          <p className="text-sm text-red-300">
            Failed to load routines. Is the backend running?
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && filtered.length === 0 && routines.length === 0 && (
        <EmptyState message="No routines found. Configure routine directories on the server to get started." />
      )}

      {/* No search results */}
      {!isLoading && !error && filtered.length === 0 && routines.length > 0 && (
        <EmptyState message="No routines match your search or filter criteria." />
      )}

      {/* Grouped routine sections */}
      {!isLoading &&
        !error &&
        sortedSources.map((source) => {
          const items = grouped.get(source) ?? [];
          const meta = SOURCE_SECTION_META[source] ?? { label: source };

          return (
            <section key={source} className="mb-8" aria-label={meta.label}>
              {/* Section header */}
              <div className="flex items-center justify-between mb-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
                  <SourceSectionIcon source={source} />
                  {meta.label}
                  <span className="text-text-muted font-normal text-xs">
                    ({items.length})
                  </span>
                </h2>
              </div>

              {/* Card grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {items.map((routine) => (
                  <RoutineCard
                    key={routine.id}
                    routine={routine}
                    onSelect={handleSelect}
                    onArchive={handleArchive}
                    onUnarchive={handleUnarchive}
                  />
                ))}
              </div>
            </section>
          );
        })}
    </div>
  );
}

function SourceSectionIcon({ source }: { source: string }) {
  switch (source) {
    case 'local':
      return (
        <svg
          className="h-4 w-4 text-accent-cyan"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
          />
        </svg>
      );
    case 'project':
      return (
        <svg
          className="h-4 w-4 text-accent-purple"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M11.42 15.17l-5.648-3.04a.562.562 0 01-.311-.51V6.837c0-.21.117-.402.303-.498l5.648-2.896a.562.562 0 01.51 0l5.648 2.896c.186.096.303.288.303.498v4.783a.562.562 0 01-.311.51l-5.648 3.04a.562.562 0 01-.494 0z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M5.461 12.13L12 15.67l6.539-3.54M12 21.67v-6"
          />
        </svg>
      );
    default:
      return (
        <svg
          className="h-4 w-4 text-text-muted"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.86-2.03a4.5 4.5 0 00-1.242-7.244l4.5-4.5a4.5 4.5 0 016.364 6.364l-1.757 1.757"
          />
        </svg>
      );
  }
}
