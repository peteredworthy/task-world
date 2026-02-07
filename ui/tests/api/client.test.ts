import { describe, it, expect } from 'vitest';
import { ApiError } from '../../src/api/client';

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
