import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ModelCostBreakdown } from '../ModelCostBreakdown';
import type { RunResponse, ModelTokenUsage } from '../../../types';

afterEach(() => {
  cleanup();
});

function makeRun(overrides: Partial<RunResponse> = {}): RunResponse {
  return {
    id: 'run-1',
    status: 'completed',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    token_usage_by_model: [],
    estimated_cost_usd: null,
    cost_disclaimer: null,
    ...overrides,
  } as RunResponse;
}

function makeUsage(overrides: Partial<ModelTokenUsage> = {}): ModelTokenUsage {
  return {
    model: 'claude-sonnet-4-6',
    gen_ai_usage_cache_read_input_tokens: 0,
    gen_ai_usage_cache_creation_input_tokens: 0,
    gen_ai_usage_input_tokens: 1000,
    gen_ai_usage_output_tokens: 500,
    gen_ai_usage_reasoning_output_tokens: 0,
    cost_usd: 0.0105,
    latency_ms: 0,
    rate_missing: false,
    ...overrides,
  };
}

describe('ModelCostBreakdown', () => {
  it('renders correct rows with model names and grand total for multi-model table', () => {
    const usages: ModelTokenUsage[] = [
      makeUsage({ model: 'claude-sonnet-4-6', cost_usd: 0.01 }),
      makeUsage({ model: 'gpt-4o', cost_usd: 0.02 }),
    ];
    render(<ModelCostBreakdown run={makeRun({ token_usage_by_model: usages })} />);

    expect(screen.getByText('claude-sonnet-4-6')).toBeInTheDocument();
    expect(screen.getByText('gpt-4o')).toBeInTheDocument();
    // Grand total = 0.01 + 0.02 = 0.03
    expect(screen.getByText('$0.0300')).toBeInTheDocument();
  });

  it('shows "cost unknown" badge when the rate is missing', () => {
    const usages: ModelTokenUsage[] = [
      makeUsage({
        model: 'mystery-model',
        rate_missing: true,
        cost_usd: 0,
      }),
    ];
    render(<ModelCostBreakdown run={makeRun({ token_usage_by_model: usages })} />);

    expect(screen.getByText('cost unknown')).toBeInTheDocument();
  });

  it('renders LegacyFallback with disclaimer when token_usage_by_model is empty', () => {
    const run = makeRun({
      token_usage_by_model: [],
      total_tokens_read: 1000,
      total_tokens_write: 500,
      cost_disclaimer: 'Estimated using default gpt-4o pricing.',
    });
    render(<ModelCostBreakdown run={run} />);

    expect(screen.getByText('Estimated using default gpt-4o pricing.')).toBeInTheDocument();
  });

  it('renders LegacyFallback with default disclaimer when token_usage_by_model is undefined', () => {
    const run = makeRun({
      token_usage_by_model: undefined as any,
      total_tokens_read: 500,
      estimated_cost_usd: 0.05,
    });
    render(<ModelCostBreakdown run={run} />);

    expect(
      screen.getByText('No per-model breakdown available — showing aggregate totals only.'),
    ).toBeInTheDocument();
  });

  it('grand total row sums cost_usd across all entries correctly', () => {
    const usages: ModelTokenUsage[] = [
      makeUsage({ model: 'model-a', cost_usd: 0.005 }),
      makeUsage({ model: 'model-b', cost_usd: 0.010 }),
      makeUsage({ model: 'model-c', cost_usd: 0.015 }),
    ];
    render(<ModelCostBreakdown run={makeRun({ token_usage_by_model: usages })} />);

    // 0.005 + 0.010 + 0.015 = 0.030
    expect(screen.getByText('$0.0300')).toBeInTheDocument();
  });

  it('renders without errors for single-model case', () => {
    const usages: ModelTokenUsage[] = [
      makeUsage({ model: 'claude-opus-4-6', cost_usd: 0.25 }),
    ];
    render(<ModelCostBreakdown run={makeRun({ token_usage_by_model: usages })} />);

    expect(screen.getByText('claude-opus-4-6')).toBeInTheDocument();
    // Cost appears in both the row and the grand total footer
    const costEls = screen.getAllByText('$0.2500');
    expect(costEls.length).toBeGreaterThanOrEqual(1);
  });
});
