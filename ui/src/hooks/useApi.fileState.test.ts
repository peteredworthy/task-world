import { describe, expect, it } from 'vitest';
import { mergeFileStateReportPages } from './useApi';
import type { FileStateReportResponse } from '../types';

function page(
  recordId: string,
  position: number,
  tokens: number,
): FileStateReportResponse {
  return {
    run_id: 'run-1', event_count: 1, from_position: position, has_more: true,
    next_position: position + 1, path_limit: 50, gatekeeper_scope: 'page',
    gatekeeper_metrics_truncated: false,
    orphan_gatekeeper_fact_count: 0,
    gatekeeper: {
      boundary_count: 1, deterministic_classifications: 0, gatekeeper_consults: 1,
      gatekeeper_resolved: 1, unresolved_residue: 0, total_classified: 1,
      gen_ai_usage_input_tokens: tokens, gen_ai_usage_output_tokens: 0,
      gen_ai_usage_cache_read_input_tokens: 0, gen_ai_usage_cache_creation_input_tokens: 0,
      cost_usd: 0, wall_time_ms: 1, models: {},
    },
    nodes: [{ node_id: 'worker', boundaries: [{
      record_id: recordId, node_id: 'worker', snapshot_id: `${recordId}-snapshot`,
      snapshot_type: 'git_commit', verdict: 'captured', classification_counts: {},
      captured_paths: [], captured_source_entries_total: 0, captured_paths_truncated: false,
      rejected_paths: [], rejected_source_entries_total: 0, rejected_paths_truncated: false,
      gatekeeper_verdicts: [], gatekeeper_verdicts_total: 0,
      gatekeeper_verdicts_truncated: false, gatekeeper_facts_total: 2,
      gatekeeper_facts_truncated: false, diff_summary: null, diff_summary_available: false,
    }] }],
  };
}

describe('mergeFileStateReportPages', () => {
  it('merges same-node boundary pages by boundary identity and aggregates metrics once', () => {
    const first = page('first', 10, 11);
    const second = page('second', 20, 22);
    const refreshedFirst = { ...first, gatekeeper_metrics_truncated: true };
    const merged = mergeFileStateReportPages([first, second, refreshedFirst], false);

    expect(merged?.nodes).toEqual([{
      node_id: 'worker',
      boundaries: expect.arrayContaining([
        expect.objectContaining({ record_id: 'first' }),
        expect.objectContaining({ record_id: 'second' }),
      ]),
    }]);
    expect(merged?.nodes[0].boundaries).toHaveLength(2);
    // The duplicate cached page is deduplicated by its boundary identity and
    // must not inflate the page-scoped aggregate.
    expect(merged?.gatekeeper?.gen_ai_usage_input_tokens).toBe(33);
    expect(merged?.gatekeeper_metrics_truncated).toBe(true);
  });
});
