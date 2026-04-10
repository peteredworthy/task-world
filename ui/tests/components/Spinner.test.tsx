import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Spinner } from '../../src/components/Spinner';

describe('Spinner', () => {
  it('renders an SVG element', () => {
    const { container } = render(<Spinner />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('uses default className', () => {
    const { container } = render(<Spinner />);
    const svg = container.querySelector('svg')!;
    expect(svg.className.baseVal).toContain('h-5 w-5');
  });

  it('accepts custom className', () => {
    const { container } = render(<Spinner className="h-4 w-4" />);
    const svg = container.querySelector('svg')!;
    expect(svg.className.baseVal).toContain('h-4 w-4');
  });
});
