import { describe, it, expect } from 'vitest';
import { formatDuration, formatTokens, formatRelativeTime } from '../../src/lib/format';

describe('formatDuration', () => {
  it('formats milliseconds', () => {
    expect(formatDuration(500)).toBe('500ms');
  });

  it('formats seconds', () => {
    expect(formatDuration(5000)).toBe('5s');
  });

  it('formats minutes and seconds', () => {
    expect(formatDuration(125000)).toBe('2m 5s');
  });

  it('formats hours and minutes', () => {
    expect(formatDuration(3_720_000)).toBe('1h 2m');
  });
});

describe('formatTokens', () => {
  it('formats small counts as-is', () => {
    expect(formatTokens(42)).toBe('42');
  });

  it('formats thousands with k suffix', () => {
    expect(formatTokens(1500)).toBe('1.5k');
  });

  it('formats millions with M suffix', () => {
    expect(formatTokens(2_500_000)).toBe('2.5M');
  });
});

describe('formatRelativeTime', () => {
  it('shows "just now" for recent times', () => {
    const now = new Date().toISOString();
    expect(formatRelativeTime(now)).toBe('just now');
  });

  it('shows minutes for recent past', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveMinAgo)).toBe('5m ago');
  });

  it('shows hours', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(threeHoursAgo)).toBe('3h ago');
  });

  it('shows days', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twoDaysAgo)).toBe('2d ago');
  });
});
