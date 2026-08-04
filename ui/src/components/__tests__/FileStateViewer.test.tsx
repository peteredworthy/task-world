import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { FileStateViewer } from '../FileStateViewer';
import type { FileStateReportResponse } from '../../types';

const report: FileStateReportResponse = {
  run_id: 'run-1',
  event_count: 1,
  from_position: 0,
  has_more: true,
  next_position: 3,
  path_limit: 1,
  gatekeeper_scope: 'page',
  gatekeeper_metrics_truncated: false,
  orphan_gatekeeper_fact_count: 0,
  gatekeeper: null,
  nodes: [{
    node_id: 'worker-1',
    boundaries: [{
      record_id: 'file-state-1',
      node_id: 'worker-1',
      snapshot_id: 'snapshot-1',
      snapshot_type: 'git_commit',
      verdict: 'captured',
      classification_counts: { build_output: 2 },
      captured_paths: [{
        path: 'dist/one.js', classification: 'build_output', reason: null,
        source: 'untracked', matched_rule: 'test', needs_gatekeeper: false,
      }],
      captured_source_entries_total: 2,
      captured_paths_truncated: true,
      rejected_paths: [],
      rejected_source_entries_total: 0,
      rejected_paths_truncated: false,
      gatekeeper_verdicts: [],
      gatekeeper_verdicts_total: 0,
      gatekeeper_verdicts_truncated: false,
      gatekeeper_facts_total: 0,
      gatekeeper_facts_truncated: false,
      diff_summary: null,
      diff_summary_available: false,
    }],
  }],
};

afterEach(cleanup);

describe('FileStateViewer', () => {
  it('shows bounded-list truncation and only requests another page on explicit action', async () => {
    const user = userEvent.setup();
    let loadMoreCalls = 0;

    render(<FileStateViewer report={report} onLoadMore={() => { loadMoreCalls += 1; }} />);

    expect(screen.getByText('Showing first 1 paths from 2 source entries; additional unique paths omitted.')).toBeInTheDocument();
    expect(loadMoreCalls).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Load more file-state records' }));
    expect(loadMoreCalls).toBe(1);
  });

  it('labels capped aggregate and model values as partial lower bounds', () => {
    render(<FileStateViewer report={{
      ...report,
      gatekeeper_metrics_truncated: true,
      gatekeeper: {
        gatekeeper_consults: 100,
        gen_ai_usage_input_tokens: 1234,
        cost_usd: 2.5,
        models: {
          'model-a': { gen_ai_usage_input_tokens: 1234, cost_usd: 2.5 },
        },
      },
    }} />);

    expect(screen.getByText(/Partial — at least gatekeeper aggregates: 100 consults/)).toBeInTheDocument();
    expect(screen.getByText(/model-a: partial — at least 1234 input tokens/)).toBeInTheDocument();
  });

  it('does not present duplicate source entries as omitted paths', () => {
    render(<FileStateViewer report={{
      ...report,
      has_more: false,
      next_position: null,
      nodes: [{
        ...report.nodes[0],
        boundaries: [{
          ...report.nodes[0].boundaries[0],
          captured_source_entries_total: 3,
          captured_paths_truncated: false,
        }],
      }],
    }} />);

    expect(screen.queryByText(/additional unique paths omitted/)).not.toBeInTheDocument();
    expect(screen.queryByText(/first 1 paths from 3 source entries/)).not.toBeInTheDocument();
  });

  it('distinguishes unavailable diff summaries from durable producer summaries', () => {
    const { rerender } = render(<FileStateViewer report={{ ...report, has_more: false, next_position: null }} />);
    expect(screen.getByText('Diff summary unavailable')).toBeInTheDocument();

    rerender(<FileStateViewer report={{
      ...report,
      has_more: false,
      next_position: null,
      nodes: [{
        ...report.nodes[0],
        boundaries: [{
          ...report.nodes[0].boundaries[0],
          diff_summary_available: true,
          diff_summary: { files_changed: 7, additions: 11, deletions: 3 },
        }],
      }],
    }} />);

    expect(screen.getByText('diff summary: 7 files changed / +11 -3')).toBeInTheDocument();
    expect(screen.queryByText('Diff summary unavailable')).not.toBeInTheDocument();
  });

  it('changes aggregate labels from partial to exact after the final page loads', () => {
    const aggregateReport = {
      ...report,
      gatekeeper: {
        gatekeeper_consults: 1,
        gen_ai_usage_input_tokens: 12,
        cost_usd: 0.1,
        models: { 'model-a': { gen_ai_usage_input_tokens: 12, cost_usd: 0.1 } },
      },
      gatekeeper_metrics_truncated: false,
    };
    const { rerender } = render(<FileStateViewer report={aggregateReport} />);

    expect(screen.getByText(/Partial — at least gatekeeper aggregates/)).toBeInTheDocument();
    expect(screen.getByText(/Additional boundary pages have not been loaded/)).toBeInTheDocument();

    rerender(<FileStateViewer report={{ ...aggregateReport, has_more: false, next_position: null }} />);

    expect(screen.getByText(/Total gatekeeper aggregates/)).toBeInTheDocument();
    expect(screen.getByText(/model-a: total 12 input tokens/)).toBeInTheDocument();
    expect(screen.queryByText(/aggregate and model totals are partial/)).not.toBeInTheDocument();
  });
});
