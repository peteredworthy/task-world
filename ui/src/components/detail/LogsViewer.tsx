import { useEffect, useRef, useState } from 'react';
import { useAttemptLogs } from '../../hooks/useApi';
import { Spinner } from '../Spinner';
import { StructuredLogsViewer } from './StructuredLogsViewer';

interface LogsViewerProps {
  runId: string;
  taskId: string;
  attemptNum: number;
}

export function LogsViewer({ runId, taskId, attemptNum }: LogsViewerProps) {
  const { data: logs, isLoading, error } = useAttemptLogs(runId, taskId, attemptNum);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewMode, setViewMode] = useState<'structured' | 'raw'>('structured');

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
  const hasActionLog = logs.action_log && logs.action_log.entries.length > 0;

  if (!hasOutput && !hasError && !hasActionLog) {
    return (
      <div className="rounded bg-bg-card border border-border px-3 py-2">
        <p className="text-xs text-text-muted italic">No agent output available</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* View mode toggle — only show when both structured and raw are available */}
      {hasActionLog && hasOutput && (
        <div className="flex items-center gap-1">
          <button
            onClick={() => setViewMode('structured')}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              viewMode === 'structured'
                ? 'bg-bg-hover text-text-primary font-semibold'
                : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            Structured
          </button>
          <button
            onClick={() => setViewMode('raw')}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              viewMode === 'raw'
                ? 'bg-bg-hover text-text-primary font-semibold'
                : 'text-text-muted hover:text-text-secondary'
            }`}
          >
            Raw
          </button>
        </div>
      )}

      {/* Structured view (default when action_log is present) */}
      {hasActionLog && viewMode === 'structured' ? (
        <StructuredLogsViewer actionLog={logs.action_log!} />
      ) : (
        <>
          {/* Raw text view (fallback for old attempts without action_log) */}
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
        </>
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
