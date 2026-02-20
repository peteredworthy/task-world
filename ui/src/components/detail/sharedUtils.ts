export function getMetric(metrics: Record<string, unknown>, key: string): number {
  const v = metrics[key];
  return typeof v === 'number' ? v : 0;
}

export const PRIORITY_ORDER = ['critical', 'expected', 'nice'] as const;

export const PRIORITY_LABELS: Record<string, string> = {
  critical: 'Required',
  expected: 'Expected',
  nice: 'Optional',
};

// Shared visual token for collapsible containers/headers so outlines stay uniform.
export const COLLAPSIBLE_BORDER_CLASS = 'border-border-hover';
export const COLLAPSIBLE_DIVIDER_CLASS = 'border-border-hover';
