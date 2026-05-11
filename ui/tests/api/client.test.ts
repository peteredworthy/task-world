import { afterEach, describe, it, expect, vi } from 'vitest';
import { ApiError, api } from '../../src/api/client';

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
});
