import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentRunners } from '../AgentRunners';
import * as apiClient from '../../api/client';
import * as apiHooks from '../../hooks/useApi';
import type { AgentRunnerOption } from '../../types/agentRunners';

vi.mock('react-router-dom', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock('../../hooks/useApi', () => ({
  useAgentRunners: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  fetchRunnerProfiles: vi.fn(),
  saveRunnerProfiles: vi.fn(),
}));

vi.mock('../../components/agentRunnerConfigUtils', () => ({
  loadAgentModelDefaults: vi.fn(() => ({})),
  saveAgentModelDefault: vi.fn(),
  loadAgentFieldDefaults: vi.fn(() => ({})),
  saveAgentFieldDefault: vi.fn(),
}));

const mockFetchRunnerProfiles = vi.mocked(apiClient.fetchRunnerProfiles);
const mockSaveRunnerProfiles = vi.mocked(apiClient.saveRunnerProfiles);
const mockUseAgents = vi.mocked(apiHooks.useAgentRunners);

function makeAgent(overrides: Partial<AgentRunnerOption> = {}): AgentRunnerOption {
  return {
    agent_type: 'cli_subprocess',
    name: 'test-runner',
    title: 'Test Runner',
    description: 'A test agent runner',
    available: true,
    detail: 'v1.0.0',
    install_hint: '',
    config_schema: [],
    quota: null,
    ...overrides,
  };
}

beforeEach(() => {
  mockFetchRunnerProfiles.mockResolvedValue({
    runner_type: 'cli_subprocess',
    profiles: {},
  });
  mockSaveRunnerProfiles.mockResolvedValue({
    runner_type: 'cli_subprocess',
    profiles: {},
  });
  mockUseAgents.mockReturnValue({
    data: [makeAgent()],
    isLoading: false,
    error: null,
  } as any);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderAndExpandProfiles() {
  render(<AgentRunners />);
  const btn = await screen.findByRole('button', { name: /model profiles/i });
  await userEvent.click(btn);
}

describe('AgentRunnerCard — Model Profiles section', () => {
  it('renders the Model Profiles toggle button', () => {
    render(<AgentRunners />);
    expect(screen.getByRole('button', { name: /model profiles/i })).toBeInTheDocument();
  });

  it('expands to show 4 profile fields when toggled', async () => {
    await renderAndExpandProfiles();

    expect(screen.getByText('Architect')).toBeInTheDocument();
    expect(screen.getByText('Designer')).toBeInTheDocument();
    expect(screen.getByText('Coder')).toBeInTheDocument();
    expect(screen.getByText('Summarizer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('loads profile data on mount and populates fields', async () => {
    mockFetchRunnerProfiles.mockResolvedValue({
      runner_type: 'cli_subprocess',
      profiles: {
        architect: 'claude-opus-4',
        coder: 'claude-sonnet-4',
      },
    });

    await renderAndExpandProfiles();

    await waitFor(() => {
      const inputs = screen.getAllByRole('textbox');
      const values = inputs.map((el) => (el as HTMLInputElement).value);
      expect(values).toContain('claude-opus-4');
      expect(values).toContain('claude-sonnet-4');
    });

    expect(mockFetchRunnerProfiles).toHaveBeenCalledWith('cli_subprocess');
  });

  it('calls saveRunnerProfiles with correct payload on Save', async () => {
    mockFetchRunnerProfiles.mockResolvedValue({
      runner_type: 'cli_subprocess',
      profiles: { architect: 'gpt-4o' },
    });

    await renderAndExpandProfiles();

    // Wait for load to populate
    await waitFor(() => {
      const inputs = screen.getAllByRole('textbox');
      const values = inputs.map((el) => (el as HTMLInputElement).value);
      expect(values).toContain('gpt-4o');
    });

    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(mockSaveRunnerProfiles).toHaveBeenCalledWith(
        'cli_subprocess',
        expect.objectContaining({
          runner_type: 'cli_subprocess',
          profiles: expect.objectContaining({ architect: 'gpt-4o' }),
        }),
      );
    });
  });

  it('shows "Saved" feedback after successful save', async () => {
    await renderAndExpandProfiles();

    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });
  });

  it('shows "Failed to save" error when saveRunnerProfiles rejects', async () => {
    mockSaveRunnerProfiles.mockRejectedValue(new Error('Network error'));

    await renderAndExpandProfiles();

    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to save')).toBeInTheDocument();
    });
  });

  it('disables Save button while saving is in progress', async () => {
    let resolveSave: (v: any) => void;
    mockSaveRunnerProfiles.mockImplementation(
      () => new Promise((resolve) => { resolveSave = resolve; }),
    );

    await renderAndExpandProfiles();

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await userEvent.click(saveBtn);

    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();

    resolveSave!({ runner_type: 'cli_subprocess', profiles: {} });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save/i })).not.toBeDisabled();
    });
  });

  it('gracefully handles fetchRunnerProfiles failure (starts with empty fields)', async () => {
    mockFetchRunnerProfiles.mockRejectedValue(new Error('Load failed'));

    await renderAndExpandProfiles();

    await waitFor(() => {
      const inputs = screen.getAllByRole('textbox');
      inputs.forEach((input) => {
        expect((input as HTMLInputElement).value).toBe('');
      });
    });
  });

  it('updates profile field values on user input', async () => {
    await renderAndExpandProfiles();

    const inputs = screen.getAllByRole('textbox');
    // First input after any model input should be architect profile
    const profileInputs = inputs.filter(
      (el) => (el as HTMLInputElement).placeholder === 'Runner default',
    );

    await userEvent.clear(profileInputs[0]);
    await userEvent.type(profileInputs[0], 'my-custom-model');

    expect((profileInputs[0] as HTMLInputElement).value).toBe('my-custom-model');
  });
});
