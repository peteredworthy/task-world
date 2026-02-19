import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { EnvFilesPanel } from '../EnvFilesPanel';
import * as apiHooks from '../../../hooks/useApi';

vi.mock('../../../hooks/useApi', () => ({
  useEnvFiles: vi.fn(),
  useEnvSnapshots: vi.fn(),
  useEnvDefaultTarget: vi.fn(),
  useRevertEnvSnapshot: vi.fn(),
  useCopyBackEnvFiles: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('EnvFilesPanel', () => {
  it('renders snapshot table with revert button', () => {
    vi.spyOn(apiHooks, 'useEnvFiles').mockReturnValue({
      data: [{ path: '.env', key: 'API_KEY', masked_value: '***' }],
      isLoading: false,
      isError: false,
    } as any);
    vi.spyOn(apiHooks, 'useEnvSnapshots').mockReturnValue({
      data: [
        {
          id: 'snap-1',
          timestamp: '2026-02-19T10:00:00Z',
          agent: 'codex',
          files: [{ path: '.env', key: 'API_KEY', masked_value: '***' }],
        },
      ],
      isLoading: false,
      isError: false,
    } as any);
    vi.spyOn(apiHooks, 'useEnvDefaultTarget').mockReturnValue({
      data: { target_path: '/tmp/target' },
      isLoading: false,
      isError: false,
    } as any);
    vi.spyOn(apiHooks, 'useRevertEnvSnapshot').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);
    vi.spyOn(apiHooks, 'useCopyBackEnvFiles').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    render(<EnvFilesPanel runId="run-1" />);

    expect(screen.getByText('Snapshot History')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revert' })).toBeInTheDocument();
  });
});
