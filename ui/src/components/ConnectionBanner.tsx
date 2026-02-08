import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '../api/client';
import { joinBaseUrl, normalizeBaseUrl } from '../lib/url';

const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_URL);

export function ConnectionBanner() {
  const [dismissed, setDismissed] = useState(false);

  const { isError, error } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      let res: Response;
      try {
        res = await fetch(joinBaseUrl(BASE_URL, '/health'));
      } catch {
        throw new ApiError(0, { detail: 'unreachable' });
      }
      if (!res.ok) throw new ApiError(res.status, null);
      return res.json();
    },
    refetchInterval: 10_000,
    retry: 2,
    retryDelay: 2000,
  });

  // Reset dismissal when connection restores
  if (!isError && dismissed) {
    setDismissed(false);
  }

  if (!isError || dismissed) return null;

  const message =
    error instanceof ApiError && error.status === 0
      ? 'Backend unreachable — retrying...'
      : 'Backend error — retrying...';

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2 bg-status-paused/10 border-b border-status-paused/30 text-sm text-status-paused">
      <div className="flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full bg-status-paused animate-pulse shrink-0" />
        <span className="font-medium">{message}</span>
      </div>
      <button
        onClick={() => setDismissed(true)}
        className="text-status-paused/70 hover:text-status-paused transition-colors text-xs font-medium shrink-0"
        aria-label="Dismiss"
      >
        Dismiss
      </button>
    </div>
  );
}
