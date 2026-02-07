import { describe, it, expect } from 'vitest';
import { recencyToMs } from '../../src/lib/recency';

describe('recencyToMs', () => {
  it('returns 1 hour in ms', () => {
    expect(recencyToMs('1h')).toBe(3_600_000);
  });

  it('returns 4 hours in ms', () => {
    expect(recencyToMs('4h')).toBe(14_400_000);
  });

  it('returns 24 hours in ms', () => {
    expect(recencyToMs('24h')).toBe(86_400_000);
  });

  it('returns 1 week in ms', () => {
    expect(recencyToMs('1w')).toBe(604_800_000);
  });

  it('returns null for empty string', () => {
    expect(recencyToMs('')).toBeNull();
  });

  it('returns null for unknown value', () => {
    expect(recencyToMs('2d')).toBeNull();
  });
});
