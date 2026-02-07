import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ConnectionIndicator } from '../../src/components/ConnectionIndicator';

describe('ConnectionIndicator', () => {
  it('renders Live for connected', () => {
    render(<ConnectionIndicator status="connected" />);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('renders Connecting for connecting', () => {
    render(<ConnectionIndicator status="connecting" />);
    expect(screen.getByText('Connecting')).toBeInTheDocument();
  });

  it('renders Disconnected for disconnected', () => {
    render(<ConnectionIndicator status="disconnected" />);
    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('renders Connection lost for failed', () => {
    render(<ConnectionIndicator status="failed" />);
    expect(screen.getByText('Connection lost')).toBeInTheDocument();
  });

  it('renders Reconnect button when failed with onReconnect', () => {
    const onReconnect = () => {};
    render(<ConnectionIndicator status="failed" onReconnect={onReconnect} />);
    expect(screen.getByText('Reconnect')).toBeInTheDocument();
  });
});
