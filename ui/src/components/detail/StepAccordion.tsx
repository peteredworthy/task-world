/**
 * @deprecated StepAccordion is no longer used by RunDetail.
 * The run detail page now renders steps as horizontal columns directly.
 * This file is kept for backward compatibility only.
 */

import type { StepSummary, RunResponse } from '../../types';
import type { StepSummarySchema } from '../../types/routines';
import { TaskCard } from './TaskCard';

interface StepAccordionProps {
  run: RunResponse;
  steps: StepSummary[];
  routineSteps: StepSummarySchema[] | undefined;
}

export function StepAccordion({ run, steps, routineSteps }: StepAccordionProps) {
  return (
    <div className="space-y-3">
      {steps.map((step, i) => {
        const stepTitle = step.title || routineSteps?.[i]?.title || step.config_id;
        const completed = step.tasks.filter(t => t.status === 'completed').length;
        const total = step.tasks.length;

        return (
          <div key={step.id} className="bg-bg-card border border-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-text-primary">
                Step {i + 1}: {stepTitle}
              </span>
              <span className="text-xs text-text-muted">
                {completed}/{total} tasks
              </span>
            </div>
            <div className="space-y-1.5">
              {step.tasks.map(task => (
                <TaskCard
                  key={task.id}
                  runId={run.id}
                  task={task}
                  taskTitle={task.title || task.config_id}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
