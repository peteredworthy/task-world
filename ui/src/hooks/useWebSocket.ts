import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getAuthToken } from '../api/client';
import { normalizeBaseUrl } from '../lib/url';

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'failed';

const MAX_RECONNECT_ATTEMPTS = 10;

function createWebSocket(
  runId: string,
  qc: ReturnType<typeof useQueryClient>,
  setStatus: (s: ConnectionStatus) => void,
  reconnectAttemptRef: React.RefObject<number>,
  reconnectTimerRef: React.RefObject<ReturnType<typeof setTimeout> | undefined>,
  scheduleReconnect: () => void,
): WebSocket {
  let baseUrl: string;
  const wsOverride = import.meta.env.VITE_WS_URL as string | undefined;
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined;

  if (wsOverride) {
    baseUrl = normalizeBaseUrl(wsOverride);
  } else if (apiUrl) {
    baseUrl = normalizeBaseUrl(apiUrl).replace(/^http/, 'ws');
  } else {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    baseUrl = proto + '//' + window.location.host;
  }

  let url = baseUrl + '/ws/runs/' + runId;

  const token = getAuthToken();
  if (token) {
    url += '?token=' + encodeURIComponent(token);
  }

  const ws = new WebSocket(url);

  ws.onopen = () => {
    setStatus('connected');
    reconnectAttemptRef.current = 0;
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      // Handle batch messages by unwrapping and processing each event
      if (data.type === 'batch' && Array.isArray(data.events)) {
        for (const evt of data.events) {
          processEvent(evt);
        }
      } else {
        processEvent(data);
      }
    } catch {
      // ignore malformed messages
    }
  };

  function processEvent(data: any) {
    const eventType = data.event_type;

    // Always invalidate the activity feed on any event
    qc.invalidateQueries({ queryKey: ['activity', runId] });

    if (eventType === 'run_status_changed') {
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    } else if (
      eventType === 'task_status_changed' ||
      eventType === 'checklist_gate_evaluated' ||
      eventType === 'grades_evaluated'
    ) {
      qc.invalidateQueries({ queryKey: ['run', runId] });
      if (data.task_id) {
        qc.invalidateQueries({ queryKey: ['task', runId, data.task_id] });
      }
    } else {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    }
  }

  ws.onclose = () => {
    const attempt = reconnectAttemptRef.current;

    if (attempt >= MAX_RECONNECT_ATTEMPTS) {
      setStatus('failed');
      return;
    }

    setStatus('disconnected');
    const delay = Math.min(1000 * Math.pow(2, attempt), 30000);
    reconnectAttemptRef.current = attempt + 1;

    reconnectTimerRef.current = setTimeout(scheduleReconnect, delay);
  };

  ws.onerror = () => {
    ws.close();
  };

  return ws;
}

export function useRunWebSocket(runId: string | undefined) {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const [status, setStatus] = useState<ConnectionStatus>(
    runId ? 'connecting' : 'disconnected'
  );

  // Track runId changes to reset status during render
  const [prevRunId, setPrevRunId] = useState(runId);
  if (runId !== prevRunId) {
    setPrevRunId(runId);
    setStatus(runId ? 'connecting' : 'disconnected');
  }

  const [reconnectTrigger, setReconnectTrigger] = useState(0);

  useEffect(() => {
    if (!runId) return;
    const id = runId;

    let cleanedUp = false;

    function connect() {
      if (cleanedUp) return;
      wsRef.current = createWebSocket(
        id,
        qc,
        setStatus,
        reconnectAttemptRef,
        reconnectTimerRef,
        connect,
      );
    }

    // Status is already set to 'connecting' during render via state tracking
    connect();

    return () => {
      cleanedUp = true;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- ref holds latest timer set by onclose
      clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [runId, qc, reconnectTrigger]);

  const reconnect = () => {
    if (status !== 'failed' || !runId) return;
    reconnectAttemptRef.current = 0;
    setStatus('connecting');
    setReconnectTrigger((n) => n + 1);
  };

  return { status, reconnect };
}
