import { useEffect, useRef, useState } from 'react';
import { useAttemptLogs } from '../../hooks/useApi';
import { Spinner } from '../Spinner';
import { StructuredLogsViewer } from './StructuredLogsViewer';

interface LogsViewerProps {
  runId: string;
  taskId: string;
  attemptNum: number;
  viewMode: 'structured' | 'raw';
  onViewModeChange: (mode: 'structured' | 'raw') => void;
  onCapabilitiesChange?: (caps: { hasStructured: boolean; hasRaw: boolean }) => void;
}

export function LogsViewer({
  runId,
  taskId,
  attemptNum,
  viewMode,
  onViewModeChange,
  onCapabilitiesChange,
}: LogsViewerProps) {
  const { data: logs, isLoading, error } = useAttemptLogs(runId, taskId, attemptNum);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [transitionKey, setTransitionKey] = useState(0);
  const hasOutput = Boolean(logs?.output && logs.output.trim().length > 0);
  const hasError = Boolean(logs?.error && logs.error.trim().length > 0);
  const hasActionLog = Boolean(logs?.action_log && logs.action_log.entries.length > 0);
  const effectiveViewMode: 'structured' | 'raw' = hasActionLog && viewMode === 'structured'
    ? 'structured'
    : hasOutput
      ? 'raw'
      : 'structured';

  // Auto-scroll to bottom when logs are loaded
  useEffect(() => {
    if (scrollRef.current && logs?.output) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs?.output]);

  useEffect(() => {
    onCapabilitiesChange?.({ hasStructured: hasActionLog, hasRaw: hasOutput });
  }, [hasActionLog, hasOutput, onCapabilitiesChange]);

  useEffect(() => {
    if (!logs) return;
    if (viewMode !== effectiveViewMode) {
      onViewModeChange(effectiveViewMode);
    }
  }, [effectiveViewMode, logs, onViewModeChange, viewMode]);

  useEffect(() => {
    if (!logs) return;
    setTransitionKey(prev => prev + 1);
  }, [effectiveViewMode, logs]);

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

  if (!hasOutput && !hasError && !hasActionLog) {
    return (
      <div className="rounded bg-bg-card border border-border px-3 py-2">
        <p className="text-xs text-text-muted italic">No agent output available</p>
      </div>
    );
  }

  return (
    <div className="p-2.5 space-y-2">
      <div
        ref={scrollRef}
        className="bg-bg-card border border-border rounded-md p-3 overflow-x-auto max-h-60 overflow-y-auto scrollbar-dark"
      >
        <div key={transitionKey} className="animate-slide-fade-in">
          {/* Structured view (default when action_log is present) */}
          {hasActionLog && effectiveViewMode === 'structured' ? (
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
                  <pre className="font-mono text-xs text-text-secondary whitespace-pre-wrap">
                    {logs.output}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>
      </div>

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
