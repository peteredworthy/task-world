import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AgentRunnerQuotaBadge } from './AgentRunnerQuotaBadge';
import type { AgentRunnerQuota } from '../types/agentRunners';

function makeQuota(overrides: Partial<AgentRunnerQuota> = {}): AgentRunnerQuota {
  return {
    balance_usd: null,
    balance_pct: null,
    max_balance_usd: null,
    label: 'Test quota',
    supports_quota: true,
    breakdown: null,
    fetched_at: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe('AgentRunnerQuotaBadge', () => {
  // Display tests

  it('renders dollar format for balance_usd', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 5.42 })} />);
    expect(screen.getByText('$5.42')).toBeInTheDocument();
  });

  it('renders percentage format for balance_pct', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 35 })} />);
    expect(screen.getByText('35%')).toBeInTheDocument();
  });

  it('shows balance_usd when both balance_usd and balance_pct are set', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 5.42, balance_pct: 35 })} />);
    expect(screen.getByText('$5.42')).toBeInTheDocument();
    expect(screen.queryByText('35%')).not.toBeInTheDocument();
  });

  // Colour via direct balance_pct

  it('applies green colour for balance_pct = 60', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 60 })} />);
    expect(screen.getByText('60%')).toHaveClass('bg-green-100');
  });

  it('applies amber colour for balance_pct = 35', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 35 })} />);
    expect(screen.getByText('35%')).toHaveClass('bg-amber-100');
  });

  it('applies red colour for balance_pct = 10', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 10 })} />);
    expect(screen.getByText('10%')).toHaveClass('bg-red-100');
  });

  // Colour boundaries

  it('applies green colour at boundary 50%', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 50 })} />);
    expect(screen.getByText('50%')).toHaveClass('bg-green-100');
  });

  it('applies amber colour at boundary 20%', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 20 })} />);
    expect(screen.getByText('20%')).toHaveClass('bg-amber-100');
  });

  it('applies red colour at 19% (just below amber boundary)', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 19 })} />);
    expect(screen.getByText('19%')).toHaveClass('bg-red-100');
  });

  // Colour via max_balance_usd path

  it('applies green colour when 80/100 = 80% via max_balance_usd', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 80, max_balance_usd: 100 })} />);
    expect(screen.getByText('$80.00')).toHaveClass('bg-green-100');
  });

  it('applies amber colour when 30/100 = 30% via max_balance_usd', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 30, max_balance_usd: 100 })} />);
    expect(screen.getByText('$30.00')).toHaveClass('bg-amber-100');
  });

  it('applies red colour when 10/100 = 10% via max_balance_usd', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 10, max_balance_usd: 100 })} />);
    expect(screen.getByText('$10.00')).toHaveClass('bg-red-100');
  });

  // No max_balance_usd or max_balance_usd = 0 → always green

  it('applies green when max_balance_usd is null or 0 (no ratio / division-by-zero guard)', () => {
    const { unmount } = render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 5 })} />);
    expect(screen.getByText('$5.00')).toHaveClass('bg-green-100');
    unmount();
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_usd: 5, max_balance_usd: 0 })} />);
    expect(screen.getByText('$5.00')).toHaveClass('bg-green-100');
  });

  // Accessibility

  it('title attribute equals quota.label', () => {
    render(<AgentRunnerQuotaBadge quota={makeQuota({ balance_pct: 60, label: 'OpenAI credits' })} />);
    expect(screen.getByTitle('OpenAI credits')).toBeInTheDocument();
  });
});
