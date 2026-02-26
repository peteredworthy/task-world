import { formatDuration, formatTokens } from '../../lib/format';
import type { RunResponse } from '../../types';

interface MetricsBarProps {
  run: RunResponse;
}

function estimateCost(tokensRead: number, tokensWrite: number): string {
  // Rough estimate: $3/1M input tokens, $15/1M output tokens
  const inputCost = (tokensRead / 1_000_000) * 3;
  const outputCost = (tokensWrite / 1_000_000) * 15;
  const total = inputCost + outputCost;
  if (total < 0.01) return '<$0.01';
  if (total < 1) return '$' + total.toFixed(2);
  return '$' + total.toFixed(2);
}

function MetricCard({
  icon,
  label,
  children,
}: {
  icon: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-bg-card rounded-lg border border-border p-4">
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-text-muted text-sm">{icon}</span>
        <span className="text-text-muted text-[11px] uppercase tracking-wide font-semibold">
          {label}
        </span>
      </div>
      <div className="text-text-primary text-2xl font-semibold">{children}</div>
    </div>
  );
}

export function MetricsBar({ run }: MetricsBarProps) {
  const tokensRead = run.total_tokens_read;
  const tokensWrite = run.total_tokens_write;
  const tokensCache = run.total_tokens_cache;
  const durationMs = run.total_duration_ms;

  // Use backend's estimated_cost_usd if available, otherwise fall back to calculation
  const costDisplay = run.estimated_cost_usd !== null
    ? '$' + run.estimated_cost_usd.toFixed(2)
    : (tokensRead > 0 || tokensWrite > 0
        ? estimateCost(tokensRead, tokensWrite)
        : '--');

  // Show "Cost" for actual API cost, "Est. Cost" for estimates
  const isActualCost = run.cost_disclaimer?.startsWith('Actual cost');

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3" role="region" aria-label="Run metrics">
      <MetricCard icon={'\u26A1'} label={tokensCache > 0 ? 'Tokens (R / W / Cache)' : 'Tokens (Read / Write)'}>
        <div className="flex items-baseline gap-1">
          <span>{formatTokens(tokensRead)}</span>
          <span className="text-text-muted text-base font-normal">/</span>
          <span>{formatTokens(tokensWrite)}</span>
          {tokensCache > 0 && (
            <>
              <span className="text-text-muted text-base font-normal">/</span>
              <span className="text-text-secondary">{formatTokens(tokensCache)}</span>
            </>
          )}
        </div>
      </MetricCard>

      <MetricCard icon={'\u23F1'} label="Duration">
        {durationMs > 0 ? formatDuration(durationMs) : '--'}
      </MetricCard>

      <MetricCard icon="$" label={isActualCost ? 'Cost' : 'Est. Cost'}>
        {costDisplay}
      </MetricCard>
    </div>
  );
}
