import { describe, expect, it } from 'vitest';
import { joinBaseUrl, normalizeBaseUrl } from '../../src/lib/url';

describe('url utils', () => {
  it('normalizes trailing slash in base url', () => {
    expect(normalizeBaseUrl('http://localhost:8000///')).toBe('http://localhost:8000');
  });

  it('returns empty base url when not configured', () => {
    expect(normalizeBaseUrl(undefined)).toBe('');
  });

  it('joins absolute path without double slash', () => {
    expect(joinBaseUrl('http://localhost:8000/', '/health')).toBe('http://localhost:8000/health');
  });

  it('joins relative path and preserves relative base mode', () => {
    expect(joinBaseUrl('', 'api/runs')).toBe('/api/runs');
  });
});

