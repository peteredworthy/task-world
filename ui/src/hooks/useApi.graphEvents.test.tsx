import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  retryGraphRead,
  useArchivalGraphSnapshot,
  useGraphEvents,
  useGraphPatchAttempts,
} from './useApi';
import { ApiError } from '../api/client';

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

describe('retryGraphRead', () => {
  it('retries a catch-up response but never repeats an obsolete position', () => {
    expect(retryGraphRead(0, new ApiError(503, {
      detail: { code: 'read_model_unavailable', retryable: true },
    }))).toBe(true);
    expect(retryGraphRead(0, new ApiError(409, {
      detail: { code: 'expected_position_mismatch', retryable: true },
    }))).toBe(false);
  });
});

function graphProjection(position: number): Response {
  return new Response(JSON.stringify({
    run_id: 'run-1',
    event_count: position,
    run_state: 'active',
    node_states: {},
    task_states: {},
    leases: {},
    ready_nodes: [],
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function archivalView(url: string, position: number): Response {
  const body = url.includes('/topology')
    ? { nodes: [{ node_id: `node-${position}` }], edges: [] }
    : url.includes('/final-blockers')
      ? { blockers: [{ blocker_id: `blocker-${position}` }] }
      : { regions: [{ region_id: `region-${position}` }] };
  return new Response(JSON.stringify({
    run_id: 'run-1',
    event_count: position,
    ...body,
    truncated: false,
    total_known: 1,
    next_cursor: null,
    partial: false,
    collection_meta: {},
  }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

function archivalHookWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retryDelay: 0 } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useArchivalGraphSnapshot', () => {
  it('restarts all three views from a fresh anchor when one view returns position 409', async () => {
    const requests: string[] = [];
    let anchorReads = 0;
    globalThis.fetch = async (input) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith('/graph')) {
        anchorReads += 1;
        return graphProjection(anchorReads === 1 ? 10 : 11);
      }
      if (url.includes('/final-blockers?expected_position=10')) {
        return new Response(JSON.stringify({
          detail: {
            code: 'expected_position_mismatch',
            expected_position: 10,
            current_position: 11,
            run_id: 'run-1',
            retryable: true,
          },
        }), { status: 409, headers: { 'Content-Type': 'application/json' } });
      }
      const position = url.includes('expected_position=10') ? 10 : 11;
      return archivalView(url, position);
    };

    const { result } = renderHook(() => useArchivalGraphSnapshot('run-1'), {
      wrapper: archivalHookWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.position).toBe(11);
    expect(result.current.data?.topology.nodes).toEqual([{ node_id: 'node-11' }]);
    expect(result.current.data?.finalBlockers.blockers).toEqual([{ blocker_id: 'blocker-11' }]);
    expect(result.current.data?.regions.regions).toEqual([{ region_id: 'region-11' }]);
    expect(requests).toEqual([
      '/api/runs/run-1/graph',
      '/api/runs/run-1/graph/topology?expected_position=10',
      '/api/runs/run-1/graph/final-blockers?expected_position=10',
      '/api/runs/run-1/graph/regions?expected_position=10',
      '/api/runs/run-1/graph',
      '/api/runs/run-1/graph/topology?expected_position=11',
      '/api/runs/run-1/graph/final-blockers?expected_position=11',
      '/api/runs/run-1/graph/regions?expected_position=11',
    ]);
  });

  it('retries a retryable 503 by assembling all three views again from a new anchor', async () => {
    const requests: string[] = [];
    let anchorReads = 0;
    let unavailableReturned = false;
    globalThis.fetch = async (input) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith('/graph')) {
        anchorReads += 1;
        return graphProjection(anchorReads === 1 ? 20 : 21);
      }
      if (url.includes('/regions?expected_position=20') && !unavailableReturned) {
        unavailableReturned = true;
        return new Response(JSON.stringify({
          detail: { code: 'read_model_unavailable', retryable: true },
        }), { status: 503, headers: { 'Content-Type': 'application/json' } });
      }
      const position = url.includes('expected_position=20') ? 20 : 21;
      return archivalView(url, position);
    };

    const { result } = renderHook(() => useArchivalGraphSnapshot('run-1'), {
      wrapper: archivalHookWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.position).toBe(21);
    expect(requests.filter((url) => url.endsWith('/graph'))).toHaveLength(2);
    for (const route of ['topology', 'final-blockers', 'regions']) {
      expect(requests).toContain(`/api/runs/run-1/graph/${route}?expected_position=20`);
      expect(requests).toContain(`/api/runs/run-1/graph/${route}?expected_position=21`);
    }
  });
});
