/**
 * RoutineSelector component
 *
 * A dropdown selector that displays routines grouped by type:
 * - Templates: System-level routines from the global routine directories
 * - Project Routines: Project-specific routines discovered from the repository
 *
 * Usage example in CreateRunModal:
 *
 * ```tsx
 * import { RoutineSelector } from '../RoutineSelector';
 *
 * // In your component:
 * <RoutineSelector
 *   repoName={form.projectId || null}
 *   branch="main"
 *   value={form.selectedRoutine}
 *   onChange={(routineId) => setForm(prev => ({ ...prev, selectedRoutine: routineId }))}
 *   autoFocus
 *   required
 * />
 * ```
 */
import { useRoutines, useRepoRoutines } from '../hooks/useApi';
import { groupRoutines } from './routineGrouping';

export interface RoutineSelection {
  routineId: string;
  isProjectRoutine: boolean;
  /** Full routine config for project routines (used as routine_embedded). */
  config?: Record<string, unknown>;
}

interface RoutineSelectorProps {
  repoName: string | null;
  branch?: string;
  value: string;
  onChange: (routineId: string) => void;
  onSelectionChange?: (selection: RoutineSelection | null) => void;
  className?: string;
  autoFocus?: boolean;
  required?: boolean;
}

export function RoutineSelector({
  repoName,
  branch = 'main',
  value,
  onChange,
  onSelectionChange,
  className = '',
  autoFocus = false,
  required = false,
}: RoutineSelectorProps) {
  const { data: templatesData, isLoading: loadingTemplates } = useRoutines({ includeArchived: false });
  const { data: projectData, isLoading: loadingProject } = useRepoRoutines(
    repoName ?? undefined,
    branch
  );

  const isLoading = loadingTemplates || (repoName ? loadingProject : false);

  // Group routines by type
  const { templates, projectRoutines } = groupRoutines(
    templatesData?.routines ?? [],
    projectData?.routines ?? []
  );

  const allRoutines = [...templates, ...projectRoutines];

  if (isLoading) {
    return (
      <select
        disabled
        className={`w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-muted shadow-sm ${className}`}
      >
        <option>Loading routines...</option>
      </select>
    );
  }

  if (allRoutines.length === 0) {
    return (
      <select
        disabled
        className={`w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-muted shadow-sm ${className}`}
      >
        <option>No routines available</option>
      </select>
    );
  }

  return (
    <select
      autoFocus={autoFocus}
      required={required}
      value={value}
      onChange={(e) => {
        const id = e.target.value;
        onChange(id);
        if (onSelectionChange) {
          if (!id) {
            onSelectionChange(null);
          } else {
            const match = allRoutines.find(r => r.id === id);
            onSelectionChange(match ? {
              routineId: id,
              isProjectRoutine: !match.isTemplate,
              config: match.config,
            } : null);
          }
        }
      }}
      className={`w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 appearance-none cursor-pointer ${className}`}
    >
      <option value="">Select a routine...</option>

      {templates.length > 0 && (
        <optgroup label="Templates">
          {templates.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
              {r.description ? ` - ${r.description}` : ''}
            </option>
          ))}
        </optgroup>
      )}

      {projectRoutines.length > 0 && (
        <optgroup label="Project Routines">
          {projectRoutines.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
              {r.description ? ` - ${r.description}` : ''}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
