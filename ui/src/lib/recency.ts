export function recencyToMs(recency: string): number | null {
  switch (recency) {
    case '1h': return 60 * 60 * 1000;
    case '4h': return 4 * 60 * 60 * 1000;
    case '24h': return 24 * 60 * 60 * 1000;
    case '1w': return 7 * 24 * 60 * 60 * 1000;
    default: return null;
  }
}
