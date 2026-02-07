import { describe, it, expect } from 'vitest';
import { runStatusColor, taskStatusColor, checklistStatusColor, priorityColor, gradeColor } from '../../src/lib/status';

describe('runStatusColor', () => {
  it.each([
    ['draft', 'bg-status-pending/20 text-status-pending'],
    ['queued', 'bg-status-paused/20 text-status-paused'],
    ['active', 'bg-status-active/20 text-status-active'],
    ['paused', 'bg-status-paused/20 text-status-paused'],
    ['completed', 'bg-status-completed/20 text-status-completed'],
    ['failed', 'bg-status-failed/20 text-status-failed'],
  ] as const)('returns correct color for %s', (status, expected) => {
    expect(runStatusColor(status)).toBe(expected);
  });
});

describe('taskStatusColor', () => {
  it.each([
    ['pending', 'bg-status-pending/20 text-status-pending'],
    ['building', 'bg-status-active/20 text-status-active'],
    ['verifying', 'bg-accent-purple/20 text-accent-purple'],
    ['completed', 'bg-status-completed/20 text-status-completed'],
    ['failed', 'bg-status-failed/20 text-status-failed'],
  ] as const)('returns correct color for %s', (status, expected) => {
    expect(taskStatusColor(status)).toBe(expected);
  });
});

describe('checklistStatusColor', () => {
  it.each([
    ['open', 'text-text-muted'],
    ['done', 'text-status-completed'],
    ['not_applicable', 'text-status-pending'],
    ['blocked', 'text-status-failed'],
  ] as const)('returns correct color for %s', (status, expected) => {
    expect(checklistStatusColor(status)).toBe(expected);
  });
});

describe('priorityColor', () => {
  it.each([
    ['critical', 'bg-status-failed/20 text-status-failed'],
    ['expected', 'bg-status-paused/20 text-status-paused'],
    ['nice', 'bg-status-pending/20 text-status-pending'],
  ] as const)('returns correct color for %s', (priority, expected) => {
    expect(priorityColor(priority)).toBe(expected);
  });
});

describe('gradeColor', () => {
  it.each([
    ['A', 'bg-grade-a/15 text-grade-a'],
    ['B', 'bg-grade-b/15 text-grade-b'],
    ['C', 'bg-grade-c/15 text-grade-c'],
    ['D', 'bg-grade-d/15 text-grade-d'],
    ['F', 'bg-grade-f/15 text-grade-f'],
    ['X', 'bg-bg-elevated text-text-muted'],
  ])('returns correct color for %s', (grade, expected) => {
    expect(gradeColor(grade)).toBe(expected);
  });
});
