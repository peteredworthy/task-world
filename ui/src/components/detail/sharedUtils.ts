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
