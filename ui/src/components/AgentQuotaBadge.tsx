/* eslint-disable react-refresh/only-export-components */
import type { AgentQuota } from '../types/agents';

type Colour = 'green' | 'amber' | 'red';

export function deriveColour(quota: AgentQuota): Colour {
  if (quota.balance_usd !== null) {
    if (quota.max_balance_usd === null || quota.max_balance_usd === 0) {
      return 'green';
    }
    const pct = (quota.balance_usd / quota.max_balance_usd) * 100;
    if (pct >= 50) return 'green';
    if (pct >= 20) return 'amber';
    return 'red';
  }
  if (quota.balance_pct !== null) {
    if (quota.balance_pct >= 50) return 'green';
    if (quota.balance_pct >= 20) return 'amber';
    return 'red';
  }
  return 'green';
}

export function formatDisplay(quota: AgentQuota): string {
  if (quota.balance_usd !== null) {
    return `$${quota.balance_usd.toFixed(2)}`;
  }
  if (quota.balance_pct !== null) {
    return `${Math.round(quota.balance_pct)}%`;
  }
  return '';
}

const colourClasses: Record<Colour, string> = {
  green: 'bg-green-100 text-green-800',
  amber: 'bg-amber-100 text-amber-800',
  red: 'bg-red-100 text-red-800',
};

interface AgentQuotaBadgeProps {
  quota: AgentQuota;
}

export function AgentQuotaBadge({ quota }: AgentQuotaBadgeProps) {
  if (quota.balance_usd === null && quota.balance_pct === null) {
    return null;
  }

  const colour = deriveColour(quota);
  const display = formatDisplay(quota);

  return (
    <span
      className={'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ' + colourClasses[colour]}
      title={quota.label}
    >
      {display}
    </span>
  );
}
