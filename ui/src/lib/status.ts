import type { ChecklistStatus, Priority, RunStatus, TaskStatus } from '../types';

export function runStatusColor(status: RunStatus): string {
  switch (status) {
    case 'draft': return 'bg-status-pending/20 text-status-pending';
    case 'active': return 'bg-status-active/20 text-status-active';
    case 'paused': return 'bg-status-paused/20 text-status-paused';
    case 'completed': return 'bg-status-completed/20 text-status-completed';
    case 'failed': return 'bg-status-failed/20 text-status-failed';
  }
}

export function taskStatusColor(status: TaskStatus): string {
  switch (status) {
    case 'pending': return 'bg-status-pending/20 text-status-pending';
    case 'building': return 'bg-status-active/20 text-status-active';
    case 'verifying': return 'bg-accent-purple/20 text-accent-purple';
    case 'completed': return 'bg-status-completed/20 text-status-completed';
    case 'failed': return 'bg-status-failed/20 text-status-failed';
  }
}

export function checklistStatusColor(status: ChecklistStatus): string {
  switch (status) {
    case 'open': return 'text-text-muted';
    case 'done': return 'text-status-completed';
    case 'not_applicable': return 'text-status-pending';
    case 'blocked': return 'text-status-failed';
  }
}

export function priorityColor(priority: Priority): string {
  switch (priority) {
    case 'critical': return 'bg-status-failed/20 text-status-failed';
    case 'expected': return 'bg-status-paused/20 text-status-paused';
    case 'nice': return 'bg-status-pending/20 text-status-pending';
  }
}

export function gradeColor(grade: string): string {
  switch (grade.toUpperCase()) {
    case 'A': return 'bg-grade-a/15 text-grade-a';
    case 'B': return 'bg-grade-b/15 text-grade-b';
    case 'C': return 'bg-grade-c/15 text-grade-c';
    case 'D': return 'bg-grade-d/15 text-grade-d';
    case 'F': return 'bg-grade-f/15 text-grade-f';
    default: return 'bg-bg-elevated text-text-muted';
  }
}

export function gradeHexColor(grade: string): string {
  switch (grade.toUpperCase()) {
    case 'A': return '#22c55e';
    case 'B': return '#3b82f6';
    case 'C': return '#eab308';
    case 'D': return '#f97316';
    case 'F': return '#ef4444';
    default: return '#64748b';
  }
}

export function statusHexColor(status: RunStatus | TaskStatus): string {
  switch (status) {
    case 'active':
    case 'completed':
    case 'building':
      return '#22c55e';
    case 'paused':
    case 'verifying':
      return '#eab308';
    case 'failed':
      return '#ef4444';
    default:
      return '#6b7280';
  }
}
