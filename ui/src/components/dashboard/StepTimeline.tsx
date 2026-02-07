import type { StepSummary } from '../../types';
import { getStepState, stepBadgeClasses } from './stepTimelineUtils';

export function StepTimeline({ steps, currentStepIndex }: { steps: StepSummary[]; currentStepIndex: number }) {
  if (steps.length === 0) return null;

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Step progress">
      {steps.map((step, i) => {
        const total = step.tasks.length;
        const completed = step.tasks.filter(t => t.status === 'completed').length;
        const state = getStepState(step, i === currentStepIndex);

        return (
          <div
            key={step.id}
            className={
              'flex items-center justify-center rounded font-mono text-[10px] font-bold leading-none ' +
              'w-7 h-[22px] ' +
              stepBadgeClasses(state)
            }
            tabIndex={0}
            role="img"
            aria-label={`Step ${i + 1}: ${completed}/${total} tasks, ${state}`}
            title={`Step ${i + 1}: ${completed}/${total} tasks`}
          >
            S{i + 1}
          </div>
        );
      })}
    </div>
  );
}
