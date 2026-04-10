import { describe, it, expect, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
import { useRef } from 'react';
import { useFocusTrap } from '../../src/hooks/useFocusTrap';

afterEach(cleanup);

function TrapHarness({ active }: { active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, active);

  return (
    <div ref={ref}>
      <button data-testid="first">First</button>
      <button data-testid="middle">Middle</button>
      <button data-testid="last">Last</button>
    </div>
  );
}

describe('useFocusTrap', () => {
  it('cycles focus from last to first on Tab', () => {
    const { container } = render(<TrapHarness active={true} />);
    const last = container.querySelector('[data-testid="last"]') as HTMLElement;
    const first = container.querySelector('[data-testid="first"]') as HTMLElement;

    last.focus();
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
  });

  it('cycles focus from first to last on Shift+Tab', () => {
    const { container } = render(<TrapHarness active={true} />);
    const first = container.querySelector('[data-testid="first"]') as HTMLElement;
    const last = container.querySelector('[data-testid="last"]') as HTMLElement;

    first.focus();
    expect(document.activeElement).toBe(first);

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it('does not trap focus when inactive', () => {
    const { container } = render(<TrapHarness active={false} />);
    const last = container.querySelector('[data-testid="last"]') as HTMLElement;

    last.focus();
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document, { key: 'Tab' });
    // Focus should not have moved to first since trap is inactive
    expect(document.activeElement).toBe(last);
  });
});
