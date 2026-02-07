import { useState } from 'react';
import { useTask, useTaskPrompt } from '../../hooks/useApi';
import { TaskStatusBadge } from '../StatusBadge';
import { Spinner } from '../Spinner';
import { AttemptTimeline, ChecklistGrades } from './shared';
import type { TaskSummary } from '../../types';

interface InspectorPanelProps {
  task: TaskSummary;
  runId: string;
  onClose: () => void;
}

export function InspectorPanel({ task, runId, onClose }: InspectorPanelProps) {
  const [showDebug, setShowDebug] = useState(false);
  const { data: detail, isLoading } = useTask(runId, task.id);
  const { data: promptData, isLoading: promptLoading } = useTaskPrompt(
    runId,
    showDebug ? task.id : undefined
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-bg-card overflow-y-auto animate-slide-in-right md:static md:inset-auto md:z-auto md:w-[340px] md:shrink-0 md:border-l md:border-border md:h-full"
      role="complementary"
      aria-label="Task inspector"
    >
      <div className="p-4 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">
            Inspector
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors"
            aria-label="Close inspector panel"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Selected Task Card */}
        <div className="rounded-lg bg-bg-elevated border border-border p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-text-muted font-mono">{task.id.slice(0, 8)}</span>
            <TaskStatusBadge status={task.status} />
          </div>
          <h3 className="text-sm font-medium text-text-primary">{task.title || task.config_id}</h3>
          <p className="text-xs text-text-muted mt-1">
            Attempt {task.current_attempt} of {task.max_attempts}
          </p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner className="h-5 w-5" />
          </div>
        ) : detail ? (
          <>
            {/* Attempt History */}
            <div>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                Attempt History
              </h3>
              <AttemptTimeline attempts={detail.attempts} />
            </div>

            {/* Checklist & Grades */}
            {detail.checklist.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                  Requirements & Grades
                </h3>
                <ChecklistGrades checklist={detail.checklist} />
              </div>
            )}
          </>
        ) : null}

        {/* Debug Section */}
        <div className="pt-2 border-t border-border">
          <button
            onClick={() => setShowDebug(!showDebug)}
            className={
              'w-full px-3 py-2 text-xs font-medium border rounded-md transition-colors ' +
              (showDebug
                ? 'text-accent-purple bg-accent-purple/10 border-accent-purple/30 hover:bg-accent-purple/20'
                : 'text-text-muted bg-bg-elevated border-border hover:bg-bg-hover hover:text-text-secondary')
            }
            aria-label={showDebug ? 'Hide debug view' : 'Show debug view'}
            aria-expanded={showDebug}
          >
            <span className="flex items-center justify-center gap-1.5">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
              {showDebug ? 'Hide Debug' : 'Debug'}
            </span>
          </button>

          {/* Debug Panel */}
          {showDebug && (
            <div className="mt-3 space-y-3 animate-slide-down">
              {promptLoading ? (
                <div className="flex justify-center py-4">
                  <Spinner className="h-4 w-4" />
                </div>
              ) : promptData ? (
                <>
                  {/* Phase indicator */}
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold text-text-muted uppercase">Phase:</span>
                    <span className={
                      'text-xs font-medium px-1.5 py-0.5 rounded ' +
                      (promptData.phase === 'building'
                        ? 'bg-status-active/20 text-status-active'
                        : 'bg-accent-purple/20 text-accent-purple')
                    }>
                      {promptData.phase}
                    </span>
                  </div>

                  {/* System Prompt */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-semibold text-text-muted uppercase">System Prompt</span>
                      <button
                        onClick={() => navigator.clipboard.writeText(promptData.system)}
                        className="text-[10px] text-text-muted hover:text-text-primary transition-colors"
                      >
                        Copy
                      </button>
                    </div>
                    <pre className="text-[11px] text-text-secondary bg-bg-card border border-border rounded-md p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono whitespace-pre-wrap">
                      {promptData.system}
                    </pre>
                  </div>

                  {/* User Prompt */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-semibold text-text-muted uppercase">User Prompt</span>
                      <button
                        onClick={() => navigator.clipboard.writeText(promptData.user)}
                        className="text-[10px] text-text-muted hover:text-text-primary transition-colors"
                      >
                        Copy
                      </button>
                    </div>
                    <pre className="text-[11px] text-text-secondary bg-bg-card border border-border rounded-md p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono whitespace-pre-wrap">
                      {promptData.user}
                    </pre>
                  </div>

                  {/* Copy Both button */}
                  <button
                    onClick={() => {
                      const fullPrompt = `SYSTEM:\n${promptData.system}\n\nUSER:\n${promptData.user}`;
                      navigator.clipboard.writeText(fullPrompt);
                    }}
                    className="w-full px-3 py-1.5 text-xs font-medium text-text-muted bg-bg-card border border-border rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
                  >
                    Copy Full Prompt
                  </button>
                </>
              ) : (
                <p className="text-xs text-text-muted italic text-center py-2">
                  No prompt available for this task
                </p>
              )}

              {/* Task ID for debugging */}
              <div className="pt-2 border-t border-border">
                <div className="text-[10px] text-text-muted space-y-1">
                  <div className="flex justify-between">
                    <span>Task ID:</span>
                    <code className="font-mono">{task.id}</code>
                  </div>
                  <div className="flex justify-between">
                    <span>Config ID:</span>
                    <code className="font-mono">{task.config_id}</code>
                  </div>
                  <div className="flex justify-between">
                    <span>Status:</span>
                    <code className="font-mono">{task.status}</code>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
