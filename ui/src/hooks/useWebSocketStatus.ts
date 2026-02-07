import { useContext } from 'react';
import { WebSocketContext } from '../context/wsContext';
import type { WebSocketContextValue } from '../context/wsContext';

export function useWebSocketStatus(): WebSocketContextValue {
  return useContext(WebSocketContext);
}
