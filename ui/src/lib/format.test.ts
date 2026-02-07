import { describe, it, expect, vi, afterEach } from 'vitest';
import { formatDuration, formatTokens, formatRelativeTime } from './format';

// ---------------------------------------------------------------------------
// formatDuration
// ---------------------------------------------------------------------------

describe('formatDuration', () => {
  it('formats sub-second durations in milliseconds', () => {
    expect(formatDuration(0)).toBe('0ms');
    expect(formatDuration(500)).toBe('500ms');
    expect(formatDuration(999)).toBe('999ms');
  });

  it('formats whole seconds', () => {
    expect(formatDuration(1000)).toBe('1s');
    expect(formatDuration(45000)).toBe('45s');
    expect(formatDuration(59999)).toBe('59s');
  });

  it('formats minutes and seconds', () => {
    expect(formatDuration(60000)).toBe('1m 0s');
    expect(formatDuration(125000)).toBe('2m 5s');
    expect(formatDuration(3599000)).toBe('59m 59s');
  });

  it('formats hours and minutes', () => {
    expect(formatDuration(3600000)).toBe('1h 0m');
    expect(formatDuration(7380000)).toBe('2h 3m');
    expect(formatDuration(86400000)).toBe('24h 0m');
  });
});

// ---------------------------------------------------------------------------
// formatTokens
// ---------------------------------------------------------------------------

describe('formatTokens', () => {
  it('formats counts below 1000 as plain numbers', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(500)).toBe('500');
    expect(formatTokens(999)).toBe('999');
  });

  it('formats thousands with k suffix', () => {
    expect(formatTokens(1000)).toBe('1.0k');
    expect(formatTokens(1500)).toBe('1.5k');
    expect(formatTokens(999999)).toBe('1000.0k');
  });

  it('formats millions with M suffix', () => {
    expect(formatTokens(1000000)).toBe('1.0M');
    expect(formatTokens(2500000)).toBe('2.5M');
  });
});

// ---------------------------------------------------------------------------
// formatRelativeTime
// ---------------------------------------------------------------------------

describe('formatRelativeTime', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns "just now" for timestamps less than 60 seconds ago', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-06-15T12:01:00Z'));

    expect(formatRelativeTime('2025-06-15T12:00:30Z')).toBe('just now');
    expect(formatRelativeTime('2025-06-15T12:00:59Z')).toBe('just now');
  });

  it('returns minutes ago for timestamps 1-59 minutes old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-06-15T12:30:00Z'));

    expect(formatRelativeTime('2025-06-15T12:29:00Z')).toBe('1m ago');
    expect(formatRelativeTime('2025-06-15T12:00:00Z')).toBe('30m ago');
  });

  it('returns hours ago for timestamps 1-23 hours old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-06-15T15:00:00Z'));

    expect(formatRelativeTime('2025-06-15T14:00:00Z')).toBe('1h ago');
    expect(formatRelativeTime('2025-06-15T12:00:00Z')).toBe('3h ago');
  });

  it('returns days ago for timestamps 1-29 days old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-06-15T12:00:00Z'));

    expect(formatRelativeTime('2025-06-14T12:00:00Z')).toBe('1d ago');
    expect(formatRelativeTime('2025-06-08T12:00:00Z')).toBe('7d ago');
  });

  it('returns locale date string for timestamps 30+ days old', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-06-15T12:00:00Z'));

    const result = formatRelativeTime('2025-01-01T00:00:00Z');
    // Should be a formatted date string, not "Xd ago"
    expect(result).not.toContain('d ago');
    expect(result).not.toContain('just now');
    // The exact format depends on the locale, but it should contain date info
    expect(result.length).toBeGreaterThan(0);
  });
});
