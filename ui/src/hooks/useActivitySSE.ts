import { useEffect, useRef, useState } from 'react';
import type { ActivityEvent } from '../types/activity';
import { joinBaseUrl, normalizeBaseUrl } from '../lib/url';

const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_URL);
const MAX_BACKOFF_MS = 30_000;

interface UseActivitySSEOptions {
  enabled?: boolean;
  onEvent?: (event: ActivityEvent) => void;
}

export function useActivitySSE(runId: string | undefined, options: UseActivitySSEOptions = {}) {
  const { enabled = true, onEvent } = options;
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const lastEventIdRef = useRef<number | null>(null);
  const attemptRef = useRef(0);

  useEffect(() => {
    if (!runId || !enabled) {
      return;
    }

    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let isMounted = true;

    const connect = () => {
      if (!isMounted) return;

      // Build URL with since_id if we have a last event
      const params = new URLSearchParams();
      if (lastEventIdRef.current !== null) {
        params.set('since_id', String(lastEventIdRef.current));
      }
      const query = params.toString();
      const url = joinBaseUrl(BASE_URL, `/api/runs/${runId}/activity/stream${query ? `?${query}` : ''}`);

      try {
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onopen = () => {
          if (isMounted) {
            setIsConnected(true);
            setConnectionError(false);
            attemptRef.current = 0;
          }
        };

        eventSource.onmessage = (e) => {
          if (!isMounted) return;

          try {
            const event: ActivityEvent = JSON.parse(e.data);
            lastEventIdRef.current = event.id;

            setEvents((prev) => [...prev, event]);

            if (onEvent) {
              onEvent(event);
            }
          } catch (err) {
            console.error('Failed to parse SSE event:', err);
          }
        };

        eventSource.onerror = () => {
          if (!isMounted) return;

          setIsConnected(false);
          setConnectionError(true);
          eventSource.close();
          eventSourceRef.current = null;

          // Exponential backoff: 1s, 2s, 4s, 8s, ... up to 30s
          const delay = Math.min(1000 * 2 ** attemptRef.current, MAX_BACKOFF_MS);
          attemptRef.current++;

          reconnectTimeout = setTimeout(() => {
            if (isMounted) {
              connect();
            }
          }, delay);
        };
      } catch {
        if (isMounted) {
          setConnectionError(true);
        }
      }
    };

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [runId, enabled, onEvent]);

  return {
    events,
    isConnected,
    connectionError,
  };
}
