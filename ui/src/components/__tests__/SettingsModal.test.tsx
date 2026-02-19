import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsModal } from '../SettingsModal';
import { SettingsContext } from '../../context/settingsContextValue';
import { useGlobalConfig } from '../../hooks/useApi';
import type { GlobalConfig } from '../../types';
import { useSettings } from '../../hooks/useSettings';

vi.mock('../../hooks/useApi', () => ({
  useGlobalConfig: vi.fn(),
}));

vi.mock('../../hooks/useSettings', () => ({
  useSettings: vi.fn(),
}));

const mockUseGlobalConfig = vi.mocked(useGlobalConfig);
const mockUseSettings = vi.mocked(useSettings);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsContext.Provider value={{ isOpen: true, open: vi.fn(), close: vi.fn() }}>
        <SettingsModal />
      </SettingsContext.Provider>
    </QueryClientProvider>,
  );
}

describe('SettingsModal', () => {
  it('renders server db_path and active_agent_types from global config', () => {
    const config: GlobalConfig = {
      db_path: '/tmp/orchestrator.db',
      active_agent_types: ['cli_subprocess', 'openhands'],
      max_recent_runs: 75,
    };

    mockUseGlobalConfig.mockReturnValue({
      data: config,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as ReturnType<typeof useGlobalConfig>);
    mockUseSettings.mockReturnValue({
      settings: { activityStreamMode: 'polling' },
      updateSettings: vi.fn(),
    });

    renderModal();

    expect(screen.getByText('Server')).toBeInTheDocument();
    expect(screen.getByText('/tmp/orchestrator.db')).toBeInTheDocument();
    expect(screen.getByText('cli_subprocess, openhands')).toBeInTheDocument();
  });
});
