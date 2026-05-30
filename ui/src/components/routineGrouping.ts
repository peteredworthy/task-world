import type { ProjectRoutineResponse, RoutineSummary } from '../types';

export interface GroupedRoutine {
  id: string;
  name: string;
  description: string | null;
  isTemplate: boolean;
  config?: Record<string, unknown>;
}

/**
 * Group routines into templates and project-specific routines.
 * Project routines take precedence so duplicate ids are only shown once.
 */
export function groupRoutines(
  templates: RoutineSummary[],
  projectRoutines: ProjectRoutineResponse[]
): { templates: GroupedRoutine[]; projectRoutines: GroupedRoutine[] } {
  const projectIds = new Set(projectRoutines.filter((r) => r.id).map((r) => r.id));
  return {
    templates: templates
      .filter((r) => r.id && !projectIds.has(r.id))
      .map((r) => ({
        id: r.id,
        name: r.name,
        description: r.description,
        isTemplate: true,
      })),
    projectRoutines: projectRoutines
      .filter((r) => r.id)
      .map((r) => ({
        id: r.id,
        name: r.name,
        description: r.description,
        isTemplate: false,
        config: r.config,
      })),
  };
}
