import { formatTokens } from '../../lib/format';
import type { ModelTokenUsage, RunResponse } from '../../types';

function isRateUnknown(usage: ModelTokenUsage): boolean {
  return (
    usage.cost_per_m_cache_read === 0 &&
    usage.cost_per_m_cache_creation === 0 &&
    usage.cost_per_m_input === 0 &&
    usage.cost_per_m_output === 0
  );
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.00';
  if (usd < 0.001) return '<$0.001';
  if (usd < 1) return '$' + usd.toFixed(4);
  return '$' + usd.toFixed(2);
}

interface ModelRowProps {
  usage: ModelTokenUsage;
}

function ModelRow({ usage }: ModelRowProps) {
  const unknown = isRateUnknown(usage);
  return (
    <tr className="border-t border-border hover:bg-bg-elevated/50 transition-colors">
      <td className="py-2 px-3 text-sm text-text-primary font-mono whitespace-nowrap">
        <div className="flex items-center gap-2">
          {usage.model}
          {unknown && (
            <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-bg-elevated border border-border text-text-muted">
              cost unknown
            </span>
          )}
        </div>
      </td>
      <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
        {formatTokens(usage.input_tokens)}
      </td>
      <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
        {formatTokens(usage.cache_read_tokens)}
      </td>
      <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
        {formatTokens(usage.cache_creation_tokens)}
      </td>
      <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
        {formatTokens(usage.output_tokens)}
      </td>
      <td className="py-2 px-3 text-sm text-right tabular-nums">
        {unknown ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span className="text-text-primary font-medium">{formatCost(usage.total_cost_usd)}</span>
        )}
      </td>
    </tr>
  );
}

interface LegacyFallbackProps {
  run: RunResponse;
}

function LegacyFallback({ run }: LegacyFallbackProps) {
  const estimateCost = (): string => {
    if (run.estimated_cost_usd !== null) {
      return '$' + run.estimated_cost_usd.toFixed(2);
    }
    const inputCost = (run.total_tokens_read / 1_000_000) * 3;
    const outputCost = (run.total_tokens_write / 1_000_000) * 15;
    const total = inputCost + outputCost;
    if (total === 0) return '—';
    if (total < 0.01) return '<$0.01';
    return '$' + total.toFixed(2);
  };

  return (
    <div className="rounded-lg border border-border bg-bg-card overflow-hidden">
      <div className="px-3 py-2 border-b border-border flex items-center gap-2">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">Token Usage</span>
        <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold bg-bg-elevated border border-border text-text-muted">
          legacy metrics
        </span>
      </div>
      <table className="w-full text-left">
        <thead>
          <tr>
            <th className="py-2 px-3 text-xs font-semibold text-text-muted">Input</th>
            <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Output</th>
            <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Cache</th>
            <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Est. Cost</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-border">
            <td className="py-2 px-3 text-sm text-text-primary tabular-nums">
              {formatTokens(run.total_tokens_read)}
            </td>
            <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
              {formatTokens(run.total_tokens_write)}
            </td>
            <td className="py-2 px-3 text-sm text-text-secondary text-right tabular-nums">
              {run.total_tokens_cache > 0 ? formatTokens(run.total_tokens_cache) : '—'}
            </td>
            <td className="py-2 px-3 text-sm text-text-primary font-medium text-right tabular-nums">
              {estimateCost()}
            </td>
          </tr>
        </tbody>
      </table>
      <div className="px-3 py-1.5 border-t border-border bg-bg-elevated/50">
        <p className="text-[11px] text-text-muted">
          {run.cost_disclaimer ?? 'No per-model breakdown available — showing aggregate totals only.'}
        </p>
      </div>
    </div>
  );
}

interface ModelCostBreakdownProps {
  run: RunResponse;
}

export function ModelCostBreakdown({ run }: ModelCostBreakdownProps) {
  const usages = run.token_usage_by_model;

  if (!usages || usages.length === 0) {
    const hasLegacy =
      run.total_tokens_read > 0 ||
      run.total_tokens_write > 0 ||
      run.total_tokens_cache > 0 ||
      run.estimated_cost_usd !== null;
    if (!hasLegacy) return null;
    return <LegacyFallback run={run} />;
  }

  const grandTotal = usages.reduce((sum, u) => sum + u.total_cost_usd, 0);
  const allUnknown = usages.every(isRateUnknown);

  return (
    <div className="rounded-lg border border-border bg-bg-card overflow-hidden">
      <div className="px-3 py-2 border-b border-border">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wide">
          Cost by Model
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="bg-bg-elevated/50">
              <th className="py-2 px-3 text-xs font-semibold text-text-muted">Model</th>
              <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Input</th>
              <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Cache Read</th>
              <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Cache Write</th>
              <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Output</th>
              <th className="py-2 px-3 text-xs font-semibold text-text-muted text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usages.map((usage, i) => (
              <ModelRow key={usage.model + '-' + i} usage={usage} />
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-border bg-bg-elevated/50">
              <td className="py-2 px-3 text-xs font-semibold text-text-secondary" colSpan={5}>
                Total
              </td>
              <td className="py-2 px-3 text-sm font-semibold text-right tabular-nums">
                {allUnknown ? (
                  <span className="text-text-muted">—</span>
                ) : (
                  <span className="text-text-primary">{formatCost(grandTotal)}</span>
                )}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
