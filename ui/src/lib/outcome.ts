export function outcomeColor(outcome: string | null): string {
  if (!outcome) return 'text-text-muted';
  if (outcome === 'passed') return 'text-status-completed';
  if (outcome === 'revision_needed') return 'text-status-paused';
  return 'text-status-failed';
}

export function outcomeLabel(outcome: string): string {
  if (outcome === 'passed') return 'Passed';
  if (outcome === 'revision_needed') return 'Revision';
  if (outcome === 'failed') return 'Failed';
  return outcome;
}
