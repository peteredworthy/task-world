import type { ConnectionStatus } from '../hooks/useWebSocket';

const STATUS_CONFIG: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: 'bg-status-active', label: 'Live' },
  connecting: { color: 'bg-status-paused', label: 'Connecting' },
  disconnected: { color: 'bg-status-failed', label: 'Disconnected' },
  failed: { color: 'bg-status-failed', label: 'Connection lost' },
};

export function ConnectionIndicator({ status, onReconnect }: { status: ConnectionStatus; onReconnect?: () => void }) {
  const config = STATUS_CONFIG[status];

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-muted" title={'WebSocket: ' + config.label}>
      <span className={'inline-block h-2 w-2 rounded-full ' + config.color} />
      {config.label}
      {status === 'failed' && onReconnect && (
        <button
          onClick={onReconnect}
          className="ml-1 text-accent-purple hover:text-accent-purple/80 underline"
        >
          Reconnect
        </button>
      )}
    </span>
  );
}
