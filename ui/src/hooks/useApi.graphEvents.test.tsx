import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useGraphEvents, useGraphPatchAttempts } from './useApi';

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('useGraphPatchAttempts', () => {
  it('uses digest identity for truncated patch IDs across bounded pages', async () => {
    globalThis.fetch = async (input) => {
      const second = String(input).includes('from_position=1');
      const attempt = (digest: string) => ({
        patch_id: 'same-prefix', patch_id_truncated: true, patch_id_original_chars: 100_000,
        patch_id_sha256: digest, proposed_by_node_id: null, proposed_by_node_id_truncated: false,
        proposed_by_node_id_original_chars: null, proposed_by_node_id_sha256: null,
        current_graph_position: 2, status: 'accepted', rejection_reason: null, diagnostics: null,
        read_set_diff: null, accepted_event_id: null, accepted_position: null, rejected_event_id: null,
        rejected_position: null, created_node_ids: [], created_node_ids_total: 0,
        created_node_ids_truncated: false, created_node_id_truncations: [], created_edge_ids: [],
        created_edge_ids_total: 0, created_edge_ids_truncated: false, created_edge_id_truncations: [],
        operations: [], operations_total: 0, operations_truncated: false, requirements: [],
        requirements_total: 0, requirements_truncated: false, reasons: [], reasons_total: 0,
        reasons_truncated: false, evidence: [], evidence_total: 0, evidence_truncated: false,
        text_truncated: false, max_text_chars: 4000, payload_truncated: false,
        payload_truncation_reasons: [], nested_identifier_truncations: [],
        nested_identifier_truncations_truncated: false,
      });
      return new Response(JSON.stringify({
        run_id: 'run-1', current_graph_position: 2, attempts: [attempt(second ? 'b'.repeat(64) : 'a'.repeat(64))],
        has_more: !second, next_position: second ? null : 1, limit: 1,
        orphan_outcome_count: 0, capped_fact_count: 0, partial: false,
      }), { status: 200 });
    };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useGraphPatchAttempts('run-1', { limit: 1 }), { wrapper });
    await waitFor(() => expect(result.current.attempts).toHaveLength(1));
    await result.current.fetchNextPage();
    await waitFor(() => expect(result.current.attempts).toHaveLength(2));
  });
});

describe('useGraphEvents', () => {
  it('resets loaded pages when the run or payload mode changes', async () => {
    const requests: string[] = [];
    globalThis.fetch = async (input) => {
      const url = String(input);
      requests.push(url);
      const runId = url.includes('/run-2/') ? 'run-2' : 'run-1';
      return new Response(JSON.stringify([{
        event_id: `${runId}-event`,
        event_type: 'node_created',
        run_id: runId,
        position: 1,
        timestamp: '2026-01-01T00:00:00Z',
        payload: { node_id: `${runId}-worker`, kind: 'worker' },
      }]), {
        status: 200,
        headers: { 'X-Has-More': 'false', 'X-Next-Position': 'null' },
      });
    };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ runId, payloadMode }: { runId: string; payloadMode: 'summary' | 'full' }) =>
        useGraphEvents(runId, { limit: 2, payloadMode }),
      {
        wrapper,
        initialProps: { runId: 'run-1', payloadMode: 'summary' as const },
      },
    );

    await waitFor(() => expect(result.current.events[0]?.run_id).toBe('run-1'));
    rerender({ runId: 'run-2', payloadMode: 'full' });
    await waitFor(() => expect(result.current.events[0]?.run_id).toBe('run-2'));

    expect(result.current.events).toHaveLength(1);
    expect(requests[0]).toContain('/run-1/graph/events');
    expect(requests[0]).toContain('payload_mode=summary');
    expect(requests[1]).toContain('/run-2/graph/events');
    expect(requests[1]).toContain('payload_mode=full');
  });
});
