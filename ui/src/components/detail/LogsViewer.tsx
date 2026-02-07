import { useEffect, useRef } from 'react';
import { useAttemptLogs } from '../../hooks/useApi';
import { Spinner } from '../Spinner';

interface LogsViewerProps {
  runId: string;
  taskId: string;
  attemptNum: number;
}

export function LogsViewer({ runId, taskId, attemptNum }: LogsViewerProps) {
  const { data: logs, isLoading, error } = useAttemptLogs(runId, taskId, attemptNum);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when logs are loaded
  useEffect(() => {
    if (scrollRef.current && logs?.output) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs?.output]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Spinner className="h-4 w-4" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded bg-status-failed/10 border border-status-failed/30 px-3 py-2">
        <p className="text-xs text-status-failed">Failed to load agent logs</p>
      </div>
    );
  }

  if (!logs) {
    return null;
  }

  const hasOutput = logs.output && logs.output.trim().length > 0;
  const hasError = logs.error && logs.error.trim().length > 0;

  if (!hasOutput && !hasError) {
    return (
      <div className="rounded bg-bg-card border border-border px-3 py-2">
        <p className="text-xs text-text-muted italic">No agent output available</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {hasOutput && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-semibold text-text-muted uppercase">Agent Output</span>
            {logs.line_count > 0 && (
              <span className="text-[10px] text-text-muted">
                {logs.line_count} line{logs.line_count !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div
            ref={scrollRef}
            className="bg-[#1a1a1a] border border-border rounded-md p-3 overflow-x-auto max-h-96 overflow-y-auto font-mono text-xs text-[#e5e5e5] whitespace-pre-wrap"
          >
            {logs.output}
          </div>
        </div>
      )}
      {hasError && (
        <div>
          <span className="text-[10px] font-semibold text-status-failed uppercase block mb-1">
            Error
          </span>
          <div className="bg-status-failed/10 border border-status-failed/30 rounded-md p-3 font-mono text-xs text-status-failed whitespace-pre-wrap">
            {logs.error}
          </div>
        </div>
      )}
    </div>
  );
}
