import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from '../../src/components/Layout';
import { CreateRunProvider } from '../../src/context/CreateRunContext';
import { SettingsProvider } from '../../src/context/SettingsContext';

afterEach(cleanup);

function renderLayout(initialPath: string = '/', outletContent: string = 'Outlet content') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <SettingsProvider>
          <CreateRunProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<div>{outletContent}</div>} />
                <Route path="/runs/:id" element={<div>{outletContent}</div>} />
              </Route>
            </Routes>
          </CreateRunProvider>
        </SettingsProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Layout', () => {
  it('renders header with Orchestrator title', () => {
    renderLayout();
    expect(screen.getByText('Orchestrator')).toBeInTheDocument();
  });

  it('renders Dashboard link in sidebar navigation', () => {
    renderLayout();
    const sidebarNav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(within(sidebarNav).getByText('Dashboard')).toBeInTheDocument();
  });

  it('Dashboard link in sidebar points to /', () => {
    renderLayout('/');
    const sidebarNav = screen.getByRole('navigation', { name: 'Main navigation' });
    const link = within(sidebarNav).getByText('Dashboard').closest('a');
    expect(link).toHaveAttribute('href', '/');
  });

  it('highlights active Dashboard link on home page', () => {
    renderLayout('/');
    const sidebarNav = screen.getByRole('navigation', { name: 'Main navigation' });
    const dashLink = within(sidebarNav).getByText('Dashboard').closest('a');
    expect(dashLink).toHaveAttribute('aria-current', 'page');
  });

  it('renders Outlet content', () => {
    renderLayout('/', 'Hello from outlet');
    expect(screen.getByText('Hello from outlet')).toBeInTheDocument();
  });

  it('Orchestrator title links to /', () => {
    renderLayout('/runs/123');
    const link = screen.getByText('Orchestrator').closest('a');
    expect(link).toHaveAttribute('href', '/');
  });
});
