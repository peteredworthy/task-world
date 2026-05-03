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
  fetchAgentRunnerModelDefaults: vi.fn(),
  saveAgentRunnerModelDefaults: vi.fn(),
}));

vi.mock('../../components/agentRunnerConfigUtils', () => ({
  loadAgentModelDefaults: vi.fn(() => ({})),
  saveAgentModelDefault: vi.fn(),
  loadAgentFieldDefaults: vi.fn(() => ({})),
  saveAgentFieldDefault: vi.fn(),
}));

const mockFetchAgentRunnerModelDefaults = vi.mocked(apiClient.fetchAgentRunnerModelDefaults);
const mockSaveAgentRunnerModelDefaults = vi.mocked(apiClient.saveAgentRunnerModelDefaults);
const mockUseAgents = vi.mocked(apiHooks.useAgentRunners);

function makeAgent(overrides: Partial<AgentRunnerOption> = {}): AgentRunnerOption {
  return {
    agent_runner_type: 'cli_subprocess',
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
  mockFetchAgentRunnerModelDefaults.mockResolvedValue({
    agent_runner_type: 'cli_subprocess',
    model_profile_defaults: {},
  });
  mockSaveAgentRunnerModelDefaults.mockResolvedValue({
    agent_runner_type: 'cli_subprocess',
    model_profile_defaults: {},
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
  const btn = await screen.findByRole('button', { name: /model defaults/i });
  await userEvent.click(btn);
}

describe('AgentRunnerCard — Model Defaults section', () => {
  it('renders the Model Defaults toggle button', () => {
    render(<AgentRunners />);
    expect(screen.getByRole('button', { name: /model defaults/i })).toBeInTheDocument();
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
    mockFetchAgentRunnerModelDefaults.mockResolvedValue({
      agent_runner_type: 'cli_subprocess',
      model_profile_defaults: {
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

    expect(mockFetchAgentRunnerModelDefaults).toHaveBeenCalledWith('cli_subprocess');
  });

  it('calls saveAgentRunnerModelDefaults with correct payload on Save', async () => {
    mockFetchAgentRunnerModelDefaults.mockResolvedValue({
      agent_runner_type: 'cli_subprocess',
      model_profile_defaults: { architect: 'gpt-4o' },
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
      expect(mockSaveAgentRunnerModelDefaults).toHaveBeenCalledWith(
        'cli_subprocess',
        expect.objectContaining({
          agent_runner_type: 'cli_subprocess',
          model_profile_defaults: expect.objectContaining({ architect: 'gpt-4o' }),
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

  it('shows "Failed to save" error when saveAgentRunnerModelDefaults rejects', async () => {
    mockSaveAgentRunnerModelDefaults.mockRejectedValue(new Error('Network error'));

    await renderAndExpandProfiles();

    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText('Failed to save')).toBeInTheDocument();
    });
  });

  it('disables Save button while saving is in progress', async () => {
    let resolveSave: (v: any) => void;
    mockSaveAgentRunnerModelDefaults.mockImplementation(
      () => new Promise((resolve) => { resolveSave = resolve; }),
    );

    await renderAndExpandProfiles();

    const saveBtn = screen.getByRole('button', { name: /save/i });
    await userEvent.click(saveBtn);

    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();

    resolveSave!({ agent_runner_type: 'cli_subprocess', model_profile_defaults: {} });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /save/i })).not.toBeDisabled();
    });
  });

  it('gracefully handles fetchAgentRunnerModelDefaults failure (starts with empty fields)', async () => {
    mockFetchAgentRunnerModelDefaults.mockRejectedValue(new Error('Load failed'));

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
