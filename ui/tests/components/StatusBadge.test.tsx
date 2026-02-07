import { describe, it, expect } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { RunStatusBadge, TaskStatusBadge } from '../../src/components/StatusBadge';

describe('RunStatusBadge', () => {
  it.each(['draft', 'queued', 'active', 'paused', 'completed', 'failed'] as const)(
    'renders %s status text',
    (status) => {
      cleanup();
      render(<RunStatusBadge status={status} />);
      expect(screen.getByText(status)).toBeInTheDocument();
    }
  );
});

describe('TaskStatusBadge', () => {
  it.each(['pending', 'building', 'verifying', 'completed', 'failed'] as const)(
    'renders %s status text',
    (status) => {
      cleanup();
      render(<TaskStatusBadge status={status} />);
      expect(screen.getByText(status)).toBeInTheDocument();
    }
  );
});
