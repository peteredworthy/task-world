import { useState } from 'react';
import type { TestRunResult } from '../../types/review';

interface TestLogsDrawerProps {
  result: TestRunResult | null;
  isOpen: boolean;
  onClose: () => void;
}

function SummaryCount({
  label,
  count,
  variant,
}: {
  label: string;
  count: number;
  variant: 'default' | 'success' | 'failed' | 'muted';
}) {
  const colorMap = {
    default: 'text-text-primary',
    success: 'text-status-success',
    failed: 'text-status-failed',
    muted: 'text-text-muted',
  };
  return (
    <div className="flex flex-col items-center rounded-md border border-border bg-bg-muted px-3 py-2">
      <span className={`text-lg font-semibold tabular-nums ${colorMap[variant]}`}>{count}</span>
      <span className="text-[10px] uppercase tracking-wide text-text-muted">{label}</span>
    </div>
  );
}

function extractFailingTests(log: string): string[] {
  const failing: string[] = [];
  // Match pytest-style FAILED lines: "FAILED tests/foo.py::test_bar - ..."
  const pytestPattern = /^FAILED\s+(\S+)/gm;
  let m: RegExpExecArray | null;
  while ((m = pytestPattern.exec(log)) !== null) {
    failing.push(m[1]);
  }
  if (failing.length > 0) return failing;

  // Match "✗" or "×" prefixed lines used by some test runners
  const symbolPattern = /^[✗×✕]\s+(.+)$/gm;
  while ((m = symbolPattern.exec(log)) !== null) {
    failing.push(m[1].trim());
  }
  return failing;
}

export function TestLogsDrawer({ result, isOpen, onClose }: TestLogsDrawerProps) {
  const [isLogExpanded, setIsLogExpanded] = useState(true);

  if (!isOpen || !result) return null;

  const summary = result.summary;
  const failingTests = extractFailingTests(result.log_output);

  return (
    <div className="flex flex-col rounded-md border border-border bg-bg-elevated overflow-hidden">
      {/* Drawer header */}
      <div className="flex items-center justify-between border-b border-border bg-bg-muted px-4 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-primary">
          Test Logs
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-0.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          aria-label="Close test logs"
        >
          ✕
        </button>
      </div>

      {/* Summary counts */}
      {summary && (
        <div className="border-b border-border px-4 py-3">
          <div className="grid grid-cols-4 gap-2">
            <SummaryCount label="Total" count={summary.total} variant="default" />
            <SummaryCount label="Passed" count={summary.passed} variant="success" />
            <SummaryCount
              label="Failed"
              count={summary.failed}
              variant={summary.failed > 0 ? 'failed' : 'muted'}
            />
            <SummaryCount label="Skipped" count={summary.skipped} variant="muted" />
          </div>
          {result.status === 'error' && (
            <p className="mt-2 text-xs text-status-failed">Test run encountered an error.</p>
          )}
          {result.duration_ms != null && (
            <p className="mt-2 text-right text-[10px] text-text-muted">
              Duration: {(result.duration_ms / 1000).toFixed(2)}s
            </p>
          )}
        </div>
      )}

      {/* Failing test names */}
      {failingTests.length > 0 && (
        <div className="border-b border-border px-4 py-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-status-failed">
            Failing Tests ({failingTests.length})
          </p>
          <ul className="flex flex-col gap-1">
            {failingTests.map((name) => (
              <li
                key={name}
                className="rounded bg-status-failed/10 px-2 py-1 font-mono text-xs text-status-failed"
              >
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Log output toggle + terminal */}
      <div className="flex min-h-0 flex-col">
        <button
          type="button"
          onClick={() => setIsLogExpanded((v) => !v)}
          className="flex items-center gap-2 border-b border-border px-4 py-2 text-left text-xs font-medium text-text-secondary transition-colors hover:bg-bg-muted hover:text-text-primary"
        >
          <span
            className={`inline-block transition-transform ${isLogExpanded ? 'rotate-90' : ''}`}
            aria-hidden="true"
          >
            ▶
          </span>
          Full Log Output
        </button>

        {isLogExpanded && (
          <pre className="min-h-0 flex-1 overflow-auto bg-bg-base p-4 font-mono text-xs leading-relaxed text-text-secondary whitespace-pre-wrap break-words">
            {result.log_output || <span className="text-text-muted italic">No log output.</span>}
          </pre>
        )}
      </div>
    </div>
  );
}
