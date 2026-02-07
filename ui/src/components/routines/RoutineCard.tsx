import type { RoutineSummary } from '../../types/routines';

interface RoutineCardProps {
  routine: RoutineSummary;
  onSelect: (routine: RoutineSummary) => void;
}

function SourceIcon({ source }: { source: string }) {
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

function SourceBadge({ source }: { source: string }) {
  const styles: Record<string, string> = {
    local: 'bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20',
    project: 'bg-accent-purple/10 text-accent-purple border-accent-purple/20',
    external: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  };

  const label = source.charAt(0).toUpperCase() + source.slice(1);
  const className = styles[source] ?? styles.external;

  return (
    <span
      className={
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ' +
        className
      }
    >
      {label}
    </span>
  );
}

export function RoutineCard({ routine, onSelect }: RoutineCardProps) {
  const totalTasks = routine.step_count;

  return (
    <div className="bg-bg-card border border-border rounded-lg p-4 flex flex-col justify-between hover:border-border-hover transition-colors">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <SourceIcon source={routine.source} />
            <h3 className="text-[15px] font-bold text-text-primary truncate">
              {routine.name}
            </h3>
          </div>
          <SourceBadge source={routine.source} />
        </div>

        {/* Description */}
        <p className="text-text-secondary text-xs leading-relaxed line-clamp-3 mb-3">
          {routine.description ?? 'No description provided.'}
        </p>
      </div>

      {/* Metadata */}
      <div>
        <div className="flex items-center gap-4 text-text-muted text-[11px] mb-3">
          <span className="inline-flex items-center gap-1" title={`${totalTasks} step(s)`}>
            <svg
              className="h-3 w-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
            {totalTasks} {totalTasks === 1 ? 'Step' : 'Steps'}
          </span>
          <span className="inline-flex items-center gap-1" title={`${routine.input_count} input(s)`}>
            <svg
              className="h-3 w-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
              />
            </svg>
            {routine.input_count} {routine.input_count === 1 ? 'Input' : 'Inputs'}
          </span>
        </div>

        {/* Action button */}
        <button
          onClick={() => onSelect(routine)}
          className="w-full bg-bg-elevated border border-border-hover rounded-md py-2 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors focus:outline-none focus:ring-2 focus:ring-accent-purple/50"
        >
          Use Routine
          <svg
            className="inline-block h-3 w-3 ml-1"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </button>
      </div>
    </div>
  );
}
