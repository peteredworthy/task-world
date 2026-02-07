import { describe, it, expect } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NotFound } from '../../src/pages/NotFound';

describe('NotFound', () => {
  it('renders "Page not found" heading', () => {
    cleanup();
    render(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>
    );
    expect(screen.getByText('Page not found')).toBeInTheDocument();
  });

  it('renders description text', () => {
    cleanup();
    render(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>
    );
    expect(screen.getByText('The page you are looking for does not exist.')).toBeInTheDocument();
  });

  it('renders "Back to Dashboard" link pointing to "/"', () => {
    cleanup();
    render(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>
    );
    const link = screen.getByRole('link', { name: 'Back to Dashboard' });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/');
  });
});
