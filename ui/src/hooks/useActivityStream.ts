import { useActivity } from './useApi';
import { useActivitySSE } from './useActivitySSE';
import { useSettings } from './useSettings';

/**
 * Unified hook for streaming activity events.
 * Uses SSE or polling based on user settings.
 */
export function useActivityStream(runId: string | undefined) {
  const { settings } = useSettings();
  const useSSE = settings.activityStreamMode === 'sse';

  // Polling mode (existing behavior)
  const pollingQuery = useActivity(runId);

  // SSE mode (new real-time behavior)
  const sseConnection = useActivitySSE(runId, {
    enabled: useSSE && !!runId,
    onEvent: () => {
      // Events are also accumulated in the hook's state, but we use onEvent for side effects if needed
    },
  });

  // Return unified interface
  if (useSSE) {
    return {
      data: {
        run_id: runId || '',
        events: sseConnection.events,
        has_more: false, // SSE streams everything
      },
      isLoading: false,
      error: sseConnection.connectionError ? new Error('SSE connection lost') : null,
      isConnected: sseConnection.isConnected,
    };
  }

  return {
    data: pollingQuery.data,
    isLoading: pollingQuery.isLoading,
    error: pollingQuery.error ? new Error('Failed to fetch activity') : null,
    isConnected: !pollingQuery.error,
  };
}
