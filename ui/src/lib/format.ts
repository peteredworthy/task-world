export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return diffMin + 'm ago';
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return diffHr + 'h ago';
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return diffDay + 'd ago';
  return date.toLocaleDateString();
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return ms + 'ms';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return sec + 's';
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (min < 60) return min + 'm ' + remSec + 's';
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return hr + 'h ' + remMin + 'm';
}

export function formatTokens(count: number): string {
  if (count < 1000) return String(count);
  if (count < 1_000_000) return (count / 1000).toFixed(1) + 'k';
  return (count / 1_000_000).toFixed(1) + 'M';
}
