import { createContext } from 'react';
import type { ConnectionStatus } from '../hooks/useWebSocket';

export interface WebSocketContextValue {
  status: ConnectionStatus;
  reconnect: () => void;
}

export const WebSocketContext = createContext<WebSocketContextValue>({
  status: 'disconnected',
  reconnect: () => {},
});
