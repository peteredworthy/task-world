import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { ErrorBoundary } from '../../src/components/ErrorBoundary';

afterEach(cleanup);

function ThrowingChild() {
  throw new Error('Test error');
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    const { getByText } = render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    );
    expect(getByText('All good')).toBeInTheDocument();
  });

  it('renders retrying UI when child throws (before max crashes)', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { getByText } = render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    // On first crash, shows auto-retry message
    expect(getByText('Connection issue — retrying...')).toBeInTheDocument();

    spy.mockRestore();
  });
});
