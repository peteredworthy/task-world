import { useTestResult } from '../../hooks/useReview';
import type { TestRunResult } from '../../types/review';

interface TestPanelProps {
  runId: string;
  hasAutoVerify?: boolean;
  /** Test run ID to poll for results; managed by parent (lifted state). */
  testRunId: string | null;
  /** Whether a test run is currently being started. */
  isStarting?: boolean;
  /** Callback to trigger starting a new test run. */
  onRunTests: () => void;
  onViewLogs?: (result: TestRunResult) => void;
  onAgentFix?: (result: TestRunResult) => void;
}

function StatusIndicator({ status }: { status: TestRunResult['status'] | 'idle' }) {
  if (status === 'idle') {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-text-muted" title="No test run yet" />;
  }
  if (status === 'running') {
    return (
      <span
        className="inline-block h-2.5 w-2.5 animate-spin rounded-full border-2 border-text-muted border-t-transparent"
        title="Tests running…"
      />
    );
  }
  if (status === 'passed') {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-status-success" title="Tests passed" />;
  }
  if (status === 'failed' || status === 'error') {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-status-failed" title="Tests failed" />;
  }
  return null;
}

function statusLabel(status: TestRunResult['status'] | 'idle'): string {
  switch (status) {
    case 'idle': return 'No tests run';
    case 'running': return 'Running…';
    case 'passed': return 'Passed';
    case 'failed': return 'Failed';
    case 'error': return 'Error';
  }
}

export function TestPanel({
  runId,
  hasAutoVerify = true,
  testRunId,
  isStarting = false,
  onRunTests,
  onViewLogs,
  onAgentFix,
}: TestPanelProps) {
  const { data: testResult } = useTestResult(runId, testRunId);

  const currentStatus: TestRunResult['status'] | 'idle' = testResult?.status ?? 'idle';
  const isRunning = currentStatus === 'running' || isStarting;
  const isFailed = currentStatus === 'failed' || currentStatus === 'error';

  if (!hasAutoVerify) {
    return (
      <div className="rounded-md border border-border bg-bg-elevated p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">Tests</h3>
        <div className="mt-4 flex flex-col items-center gap-2 py-2 text-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-text-muted opacity-50"
            aria-hidden="true"
          >
            <path d="M9 11l3 3L22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </svg>
          <p className="text-xs text-text-muted">No test commands configured</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-bg-elevated p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">Tests</h3>

      {/* Status row — skeleton while a run is starting but no result yet */}
      {isStarting && !testResult ? (
        <div className="mt-3 flex items-center gap-2" aria-label="Starting test run">
          <span className="skeleton h-2.5 w-2.5 shrink-0 rounded-full" />
          <span className="skeleton h-3 w-20" />
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-2">
          <StatusIndicator status={currentStatus} />
          <span className="text-xs text-text-secondary">{statusLabel(currentStatus)}</span>
          {testResult?.summary && (
            <span className="ml-auto text-xs text-text-muted">
              {testResult.summary.passed}/{testResult.summary.total} passed
            </span>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-3 flex flex-col gap-2">
        <button
          type="button"
          onClick={onRunTests}
          disabled={isRunning}
          className="w-full rounded border border-border px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:bg-bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRunning ? 'Running…' : 'Run Tests'}
        </button>

        {testResult && (
          <button
            type="button"
            onClick={() => onViewLogs?.(testResult)}
            className="w-full rounded border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:bg-bg-muted hover:text-text-primary"
          >
            View Logs
          </button>
        )}

        {isFailed && testResult && (
          <button
            type="button"
            onClick={() => onAgentFix?.(testResult)}
            className="w-full rounded border border-status-failed/40 bg-status-failed/10 px-3 py-1.5 text-xs font-medium text-status-failed transition-colors hover:bg-status-failed/20"
          >
            Use Agent to Fix Tests
          </button>
        )}
      </div>
    </div>
  );
}
