import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
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

  it('renders recovery UI when child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    const { getByText } = render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    expect(getByText('Something went wrong')).toBeInTheDocument();
    expect(getByText('Reload')).toBeInTheDocument();

    spy.mockRestore();
  });

  it('reload button calls window.location.reload', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const reloadSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload: reloadSpy },
      writable: true,
      configurable: true,
    });

    const { getByText } = render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    );

    fireEvent.click(getByText('Reload'));
    expect(reloadSpy).toHaveBeenCalled();

    spy.mockRestore();
  });
});
