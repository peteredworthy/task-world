import { useState, useEffect } from 'react';
import { Spinner } from '../Spinner';

interface WaitingIndicatorProps {
  startedAt: string | null;
  onCancel?: () => void;
}

export function WaitingIndicator({ startedAt, onCancel }: WaitingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const start = new Date(startedAt).getTime();

    function tick() {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  const min = Math.floor(elapsed / 60);
  const sec = elapsed % 60;
  const display = min > 0
    ? min + ':' + String(sec).padStart(2, '0')
    : sec + 's';

  return (
    <div className="flex items-center gap-3 bg-accent-purple/10 border border-accent-purple/30 rounded-md px-4 py-3">
      <Spinner className="h-4 w-4" />
      <div className="flex-1">
        <span className="text-sm font-medium text-accent-purple">Waiting for agent to submit work...</span>
        <span className="text-xs text-text-muted ml-2">{display}</span>
      </div>
      {onCancel && (
        <button
          onClick={onCancel}
          className="text-xs text-status-failed hover:text-status-failed/80 font-medium"
        >
          Cancel
        </button>
      )}
    </div>
  );
}
