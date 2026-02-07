import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyState } from '../../src/components/EmptyState';

describe('EmptyState', () => {
  it('renders the message', () => {
    render(<EmptyState message="No items found" />);
    expect(screen.getByText('No items found')).toBeInTheDocument();
  });
});
