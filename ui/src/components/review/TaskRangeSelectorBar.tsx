import { useEffect, useMemo, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { api } from '../../api/client';
import { taskStatusColor } from '../../lib/status';
import type { RunResponse, TaskStatus } from '../../types';

export interface SharedDiffSelection {
  scope: 'aggregate' | 'task';
  ref?: string;
  summary: string;
}

interface TaskRangeSelectorBarProps {
  runId: string;
  run?: RunResponse;
  onSelectionChange: (selection: SharedDiffSelection) => void;
}

interface TimelineTask {
  id: string;
  shortLabel: string;
  title: string;
  stepLabel: string;
  stepTitle: string;
  stepIndex: number;
  taskIndexInStep: number;
  status: TaskStatus;
  startCommit?: string;
  endCommit?: string;
  ref?: string;
}

function taskTitle(task: TimelineTask): string {
  return `${task.shortLabel} · ${task.title}`;
}

function selectionSummary(
  tasks: TimelineTask[],
  startId: string | null,
  endId: string | null,
  allShortcutSelected: boolean,
): string {
  if (allShortcutSelected) return 'All work';

  const startIdx = tasks.findIndex((t) => t.id === startId);
  const endIdx = tasks.findIndex((t) => t.id === endId);
  if (startIdx < 0 || endIdx < 0) return 'No selection';

  const [lo, hi] = startIdx <= endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
  const start = tasks[lo];
  const end = tasks[hi];
  if (!start || !end) return 'No selection';
  if (start.id === end.id) return taskTitle(start);
  return `${taskTitle(start)} to ${taskTitle(end)}`;
}

export function TaskRangeSelectorBar({ runId, run, onSelectionChange }: TaskRangeSelectorBarProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [anchorTaskId, setAnchorTaskId] = useState<string | null>(null);
  const [selectedStartTaskId, setSelectedStartTaskId] = useState<string | null>(null);
  const [selectedEndTaskId, setSelectedEndTaskId] = useState<string | null>(null);

  const flatTasks = useMemo(
    () =>
      (run?.steps ?? []).flatMap((step, si) =>
        step.tasks.map((task, ti) => ({
          id: task.id,
          shortLabel: `S${si + 1}.${ti + 1}`,
          stepLabel: `Step ${si + 1}`,
          stepTitle: step.title || step.config_id || `Step ${si + 1}`,
          stepIndex: si,
          taskIndexInStep: ti,
          title: task.title || task.config_id,
          status: task.status,
        })),
      ),
    [run],
  );

  const taskMetaById = useMemo(
    () =>
      new Map(
        flatTasks.map((task) => [
          task.id,
          {
            shortLabel: task.shortLabel,
            stepLabel: task.stepLabel,
            stepTitle: task.stepTitle,
            stepIndex: task.stepIndex,
            taskIndexInStep: task.taskIndexInStep,
            title: task.title,
            status: task.status,
          },
        ]),
      ),
    [flatTasks],
  );

  const taskDetailQueries = useQueries({
    queries: flatTasks.map((t) => ({
      queryKey: ['task', runId, t.id],
      queryFn: () => api.getTask(runId, t.id),
      staleTime: 60_000,
      enabled: !!run,
    })),
  });

  const timelineTasks: TimelineTask[] = flatTasks.map((t, i) => {
    const detail = taskDetailQueries[i]?.data;
    // Sort attempts ascending so we can find the earliest start and latest end.
    // Revision cycles often leave start_commit null on later attempts, so we
    // use the first attempt that has a start_commit and the last that has an end_commit.
    const sortedAttempts = detail?.attempts
      ? [...detail.attempts].sort((a, b) => a.attempt_num - b.attempt_num)
      : [];
    const startCommit =
      sortedAttempts.find((a) => a.start_commit != null)?.start_commit ?? undefined;
    const endCommit =
      [...sortedAttempts].reverse().find((a) => a.end_commit != null)?.end_commit ?? undefined;
    const meta = taskMetaById.get(t.id);
    return {
      id: t.id,
      shortLabel: meta?.shortLabel ?? t.shortLabel,
      title: meta?.title ?? t.title,
      stepLabel: meta?.stepLabel ?? t.stepLabel,
      stepTitle: meta?.stepTitle ?? t.stepTitle,
      stepIndex: meta?.stepIndex ?? t.stepIndex,
      taskIndexInStep: meta?.taskIndexInStep ?? t.taskIndexInStep,
      status: meta?.status ?? t.status,
      startCommit,
      endCommit,
      ref: startCommit && endCommit ? `${startCommit}..${endCommit}` : undefined,
    };
  });

  const selectableTasks = timelineTasks.filter((t) => t.ref);
  const firstSelectable = selectableTasks[0];
  const lastSelectable = selectableTasks[selectableTasks.length - 1];

  useEffect(() => {
    if (selectableTasks.length === 0) {
      setAnchorTaskId(null);
      setSelectedStartTaskId(null);
      setSelectedEndTaskId(null);
      return;
    }

    const validIds = new Set(timelineTasks.map((t) => t.id));
    const hasValidSelection =
      selectedStartTaskId != null &&
      selectedEndTaskId != null &&
      validIds.has(selectedStartTaskId) &&
      validIds.has(selectedEndTaskId);

    if (!hasValidSelection) {
      setAnchorTaskId(firstSelectable.id);
      setSelectedStartTaskId(firstSelectable.id);
      setSelectedEndTaskId(lastSelectable.id);
    } else if (anchorTaskId && !validIds.has(anchorTaskId)) {
      setAnchorTaskId(firstSelectable.id);
    }
  }, [
    anchorTaskId,
    selectedStartTaskId,
    selectedEndTaskId,
    selectableTasks,
    timelineTasks,
    firstSelectable,
    lastSelectable,
  ]);

  const startIdx = selectedStartTaskId ? timelineTasks.findIndex((t) => t.id === selectedStartTaskId) : -1;
  const endIdx = selectedEndTaskId ? timelineTasks.findIndex((t) => t.id === selectedEndTaskId) : -1;
  const [normalizedStartIdx, normalizedEndIdx] =
    startIdx >= 0 && endIdx >= 0 && startIdx > endIdx ? [endIdx, startIdx] : [startIdx, endIdx];

  const normalizedRangeStart = normalizedStartIdx >= 0 ? timelineTasks[normalizedStartIdx] : undefined;
  const normalizedRangeEnd = normalizedEndIdx >= 0 ? timelineTasks[normalizedEndIdx] : undefined;

  const allShortcutSelected =
    !!firstSelectable &&
    !!lastSelectable &&
    normalizedRangeStart?.id === firstSelectable.id &&
    normalizedRangeEnd?.id === lastSelectable.id;

  const summary = selectionSummary(
    timelineTasks,
    selectedStartTaskId,
    selectedEndTaskId,
    allShortcutSelected,
  );

  const rangeRef =
    normalizedRangeStart?.startCommit && normalizedRangeEnd?.endCommit
      ? `${normalizedRangeStart.startCommit}..${normalizedRangeEnd.endCommit}`
      : undefined;

  const stepGroups = useMemo(() => {
    const groups: Array<{
      stepIndex: number;
      stepLabel: string;
      stepTitle: string;
      tasks: TimelineTask[];
    }> = [];
    for (const task of timelineTasks) {
      const last = groups[groups.length - 1];
      if (!last || last.stepIndex !== task.stepIndex) {
        groups.push({
          stepIndex: task.stepIndex,
          stepLabel: task.stepLabel,
          stepTitle: task.stepTitle,
          tasks: [task],
        });
      } else {
        last.tasks.push(task);
      }
    }
    return groups;
  }, [timelineTasks]);

  useEffect(() => {
    if (selectableTasks.length === 0 || !rangeRef) {
      onSelectionChange({ scope: 'aggregate', summary: 'All work' });
      return;
    }
    onSelectionChange({ scope: 'task', ref: rangeRef, summary });
  }, [onSelectionChange, rangeRef, selectableTasks.length, summary]);

  return (
    <div className="mb-3 rounded-lg border border-border bg-bg-elevated/90">
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-bg-muted/40 transition-colors"
        aria-expanded={isExpanded}
      >
        <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Task Range
        </span>
        <span className="min-w-0 flex-1 truncate text-xs text-text-primary">Showing: {summary}</span>
        <span className="hidden md:flex items-center gap-2 text-[10px] text-text-muted">
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-status-passed" />
            Done
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            Active
          </span>
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 14 14"
          fill="none"
          className={`shrink-0 text-text-muted transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        >
          <path
            d="M3.5 5.25L7 8.75L10.5 5.25"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {isExpanded && (
        <div className="border-t border-border px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                if (!firstSelectable || !lastSelectable) return;
                setAnchorTaskId(firstSelectable.id);
                setSelectedStartTaskId(firstSelectable.id);
                setSelectedEndTaskId(lastSelectable.id);
              }}
              disabled={!firstSelectable || !lastSelectable}
              className="rounded-md border border-border bg-bg-muted px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:text-text-primary hover:bg-bg-card transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            >
              All Work
            </button>
            <p className="text-[11px] text-text-muted">
              Click a task to select it. Shift-click to select a range.
            </p>
          </div>

          <div className="mt-3 overflow-x-auto pb-1">
            {timelineTasks.length === 0 ? (
              <p className="text-xs text-text-muted">No task timeline available.</p>
            ) : (
              <div className="inline-flex min-w-full items-start gap-3">
                {stepGroups.map((group) => {
                  const taskIndices = group.tasks.map((t) =>
                    timelineTasks.findIndex((tt) => tt.id === t.id),
                  );
                  const groupHasInRange =
                    normalizedStartIdx >= 0 &&
                    normalizedEndIdx >= 0 &&
                    taskIndices.some((i) => i >= normalizedStartIdx && i <= normalizedEndIdx);
                  const groupAllDisabled = group.tasks.every((t) => !t.ref);

                  const stepRibbonClass =
                    'h-5 min-w-0 rounded-md border px-2 text-[10px] font-medium leading-none flex items-center truncate ' +
                    (groupHasInRange
                      ? 'bg-emerald-500/8 border-emerald-500/20 text-emerald-200/90'
                      : groupAllDisabled
                        ? 'bg-bg-muted/50 border-border/60 text-text-muted'
                        : 'bg-bg-muted border-border text-text-muted');

                  return (
                    <div key={group.stepIndex} className="flex flex-col gap-1.5">
                      <div className={stepRibbonClass} title={`${group.stepLabel} · ${group.stepTitle}`}>
                        {group.stepLabel} · {group.stepTitle}
                      </div>
                      <div className="flex gap-1.5">
                        {group.tasks.map((task) => {
                          const idx = timelineTasks.findIndex((tt) => tt.id === task.id);
                          const isDisabled = !task.ref;
                          const inRange =
                            normalizedStartIdx >= 0 &&
                            normalizedEndIdx >= 0 &&
                            idx >= normalizedStartIdx &&
                            idx <= normalizedEndIdx;
                          const isStart = normalizedRangeStart?.id === task.id;
                          const isEnd = normalizedRangeEnd?.id === task.id;
                          const isSingle = isStart && isEnd;

                          // Base: fixed min-width, content-driven width (w-max), capped at min.
                          // Hover: cap rises to 200% so the chip only grows as wide as the text needs.
                          let chipClass =
                            'shrink-0 rounded-md border text-left flex flex-col ' +
                            'min-w-[14.25rem] h-[3.6rem] w-max max-w-[14.25rem] ' +
                            'transition-[max-width,background-color,border-color] duration-300 ease-out ';
                          if (isDisabled) {
                            chipClass +=
                              'border-border/70 bg-bg-card/60 text-text-muted opacity-60 cursor-not-allowed';
                          } else if (isSingle) {
                            chipClass += 'hover:max-w-[28.5rem] border-blue-500/40 bg-blue-500/14 text-blue-300';
                          } else if (inRange) {
                            chipClass += 'hover:max-w-[28.5rem] border-emerald-500/35 bg-emerald-500/10 text-emerald-200';
                          } else {
                            chipClass +=
                              'hover:max-w-[28.5rem] border-border hover:border-border-hover hover:bg-bg-card text-text-secondary';
                          }

                          return (
                            <button
                              key={task.id}
                              type="button"
                              disabled={isDisabled}
                              title={
                                isDisabled
                                  ? `${taskTitle(task)} · No recorded commit range`
                                  : `${taskTitle(task)} · ${task.stepLabel}`
                              }
                              onClick={(e) => {
                                if (!task.ref) return;
                                if (e.shiftKey && anchorTaskId) {
                                  setSelectedStartTaskId(anchorTaskId);
                                  setSelectedEndTaskId(task.id);
                                  return;
                                }
                                setAnchorTaskId(task.id);
                                setSelectedStartTaskId(task.id);
                                setSelectedEndTaskId(task.id);
                              }}
                              className={chipClass}
                            >
                              <div className="flex min-h-0 flex-1 flex-col px-2.5 py-1.5">
                                <div className="flex items-start justify-between gap-2">
                                  <span className="font-mono text-[10px] font-semibold tracking-wide text-current">
                                    {task.shortLabel}
                                  </span>
                                  <span
                                    className={
                                      'shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ' +
                                      taskStatusColor(task.status)
                                    }
                                  >
                                    {String(task.status).replaceAll('_', ' ')}
                                  </span>
                                </div>
                                <p
                                  className="mt-0.5 text-xs font-medium leading-snug text-current truncate whitespace-nowrap"
                                  title={task.title}
                                >
                                  {task.title}
                                </p>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {selectableTasks.length === 0 && (
            <p className="mt-2 text-xs text-text-muted">No tasks with recorded commit ranges are available yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
