import { useState } from 'react';
import type { AttemptSchema } from '../../types';
import { formatDuration, formatTokens } from '../../lib/format';

function getMetric(metrics: Record<string, unknown>, key: string): number {
  const v = metrics[key];
  return typeof v === 'number' ? v : 0;
}

export function AttemptHistory({ attempts }: { attempts: AttemptSchema[] }) {
  const [expanded, setExpanded] = useState(false);

  if (attempts.length === 0) {
    return <p className="text-xs text-text-muted italic">No attempts yet</p>;
  }

  const shown = expanded ? attempts : attempts.slice(-1);

  return (
    <div>
      {attempts.length > 1 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-accent-purple hover:text-accent-purple/80 mb-1"
        >
          {expanded ? 'Show latest only' : 'Show all ' + attempts.length + ' attempts'}
        </button>
      )}
      <div className="space-y-1.5">
        {shown.map(att => {
          const durationMs = getMetric(att.metrics, 'duration_ms');
          const tokensRead = getMetric(att.metrics, 'tokens_read');
          const tokensWrite = getMetric(att.metrics, 'tokens_write');
          return (
            <div key={att.id} className="flex items-center gap-3 text-xs text-text-muted bg-bg-elevated rounded px-2 py-1.5">
              <span className="font-medium">#{att.attempt_num}</span>
              {att.outcome && (
                <span className={att.outcome === 'passed' ? 'text-status-completed' : att.outcome === 'revision_needed' ? 'text-status-paused' : 'text-status-failed'}>
                  {att.outcome === 'passed' ? 'Passed' : att.outcome === 'revision_needed' ? 'Revision' : att.outcome === 'failed' ? 'Failed' : att.outcome}
                </span>
              )}
              {durationMs > 0 && (
                <span>{formatDuration(durationMs)}</span>
              )}
              {tokensRead > 0 && (
                <span>{formatTokens(tokensRead)} read</span>
              )}
              {tokensWrite > 0 && (
                <span>{formatTokens(tokensWrite)} write</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
