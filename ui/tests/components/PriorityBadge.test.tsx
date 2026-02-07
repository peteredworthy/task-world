import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PriorityBadge } from '../../src/components/PriorityBadge';

describe('PriorityBadge', () => {
  it.each(['critical', 'expected', 'nice'] as const)(
    'renders %s priority',
    (priority) => {
      render(<PriorityBadge priority={priority} />);
      expect(screen.getByText(priority)).toBeInTheDocument();
    }
  );
});
