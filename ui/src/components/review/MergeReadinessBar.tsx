import { useState } from 'react';
import { useMergeReadiness } from '../../hooks/useReview';
import { Spinner } from '../Spinner';
import type { Gate } from '../../types/review';

interface MergeReadinessBarProps {
  runId: string;
  onMergeCommit: () => void;
}

function GateIcon({ status }: { status: Gate['status'] }) {
  if (status === 'pass') {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-status-passed shrink-0"
        aria-hidden="true"
      >
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  if (status === 'fail') {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-status-failed shrink-0"
        aria-hidden="true"
      >
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    );
  }
  return <Spinner className="h-3.5 w-3.5 shrink-0" />;
}

function GateItem({ gate }: { gate: Gate }) {
  const labelColor =
    gate.status === 'pass'
      ? 'text-status-passed'
      : gate.status === 'fail'
        ? 'text-status-failed'
        : 'text-text-muted';

  return (
    <div className="flex items-center gap-1.5" title={gate.description}>
      <GateIcon status={gate.status} />
      <span className={`text-xs font-medium ${labelColor}`}>{gate.description}</span>
    </div>
  );
}

export function MergeReadinessBar({ runId, onMergeCommit }: MergeReadinessBarProps) {
  const { data: readiness, isLoading } = useMergeReadiness(runId);
  const [showTooltip, setShowTooltip] = useState(false);

  const isReady = readiness?.ready ?? false;
  const gates = readiness?.gates ?? [];

  const failingGates = gates.filter((g) => g.status !== 'pass');
  const tooltipText =
    failingGates.length > 0
      ? `${failingGates.length} gate${failingGates.length === 1 ? '' : 's'} not yet passing`
      : '';

  return (
    <div className="shrink-0 border-t border-border bg-bg-primary px-4 py-3">
      <div className="flex items-center gap-4 flex-wrap">
        {/* Gate indicators */}
        <div className="flex items-center gap-4 flex-wrap flex-1 min-w-0">
          {isLoading && gates.length === 0 ? (
            <div className="flex items-center gap-4" aria-label="Loading readiness gates">
              {[80, 100, 90].map((w, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="skeleton h-3.5 w-3.5 shrink-0 rounded-full" />
                  <span className="skeleton h-3" style={{ width: `${w}px` }} />
                </div>
              ))}
            </div>
          ) : (
            gates.map((gate) => <GateItem key={gate.name} gate={gate} />)
          )}
        </div>

        {/* Commit Merge Back button */}
        <div
          className="relative shrink-0"
          onMouseEnter={() => { if (!isReady) setShowTooltip(true); }}
          onMouseLeave={() => setShowTooltip(false)}
        >
          <button
            type="button"
            onClick={isReady ? onMergeCommit : undefined}
            disabled={!isReady}
            aria-disabled={!isReady}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              isReady
                ? 'bg-accent-blue text-white hover:bg-accent-blue/90 cursor-pointer'
                : 'bg-bg-muted text-text-muted cursor-not-allowed opacity-50'
            }`}
          >
            Commit Merge Back
          </button>
          {showTooltip && tooltipText && (
            <div className="absolute bottom-full right-0 mb-2 whitespace-nowrap rounded-md bg-bg-elevated border border-border px-3 py-1.5 text-xs text-text-secondary shadow-lg pointer-events-none z-10">
              {tooltipText}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
