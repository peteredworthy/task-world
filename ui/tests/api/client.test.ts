import { afterEach, describe, it, expect, vi } from 'vitest';
import {
  ApiError,
  api,
  isExpectedGraphPositionMismatch,
  isRetryableGraphReadError,
} from '../../src/api/client';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ApiError', () => {
  it('has correct name', () => {
    const err = new ApiError(404, { detail: 'not found' });
    expect(err.name).toBe('ApiError');
  });

  it('has correct status', () => {
    const err = new ApiError(500, null);
    expect(err.status).toBe(500);
  });

  it('has correct body', () => {
    const body = { detail: 'bad request' };
    const err = new ApiError(400, body);
    expect(err.body).toBe(body);
  });

  it('has descriptive message', () => {
    const err = new ApiError(422, null);
    expect(err.message).toBe('API error 422');
  });

  it('is an instance of Error', () => {
    const err = new ApiError(401, null);
    expect(err).toBeInstanceOf(Error);
  });
});

describe('api', () => {
  it('fetches pending clarifications from the server route', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('null', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await api.getPendingClarification('run-1', 'task-1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs/run-1/tasks/task-1/clarifications/pending',
      expect.any(Object),
    );
  });

  it('passes one graph anchor to every archival view route', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(
      JSON.stringify({
        run_id: 'run-1', event_count: 12, nodes: [], edges: [], blockers: [], regions: [],
        truncated: false, total_known: 0, next_cursor: null, partial: false, collection_meta: {},
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));

    await api.getRunGraphTopology('run-1', { expectedPosition: 12 });
    await api.getRunGraphFinalBlockers('run-1', { expectedPosition: 12 });
    await api.getRunGraphRegions('run-1', { expectedPosition: 12 });

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls).toEqual([
      '/api/runs/run-1/graph/topology?expected_position=12',
      '/api/runs/run-1/graph/final-blockers?expected_position=12',
      '/api/runs/run-1/graph/regions?expected_position=12',
    ]);
  });

  it('classifies graph catch-up and obsolete-anchor errors differently', () => {
    const unavailable = new ApiError(503, {
      detail: { code: 'read_model_unavailable', retryable: true },
    });
    const mismatch = new ApiError(409, {
      detail: { code: 'expected_position_mismatch', retryable: true },
    });

    expect(isRetryableGraphReadError(unavailable)).toBe(true);
    expect(isExpectedGraphPositionMismatch(unavailable)).toBe(false);
    expect(isRetryableGraphReadError(mismatch)).toBe(false);
    expect(isExpectedGraphPositionMismatch(mismatch)).toBe(true);
  });
});
