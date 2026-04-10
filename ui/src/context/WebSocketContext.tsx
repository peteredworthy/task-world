import { useRunWebSocket } from '../hooks/useWebSocket';
import { WebSocketContext } from './wsContext';

export function WebSocketProvider({ runId, children }: { runId: string | undefined; children: React.ReactNode }) {
  const value = useRunWebSocket(runId);
  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>;
}
