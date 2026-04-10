import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GradeBadge } from '../../src/components/GradeBadge';

describe('GradeBadge', () => {
  it.each(['A', 'B', 'C', 'D', 'F'])(
    'renders grade %s',
    (grade) => {
      render(<GradeBadge grade={grade} />);
      expect(screen.getByText(grade)).toBeInTheDocument();
    }
  );
});
