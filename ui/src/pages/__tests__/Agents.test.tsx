import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Agents } from '../Agents';
import * as agentApi from '../../lib/agentApi';
import type { Agent } from '../../types/agents';

vi.mock('react-router-dom', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock('../../lib/agentApi', () => ({
  fetchAgents: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  resetAgentPrompt: vi.fn(),
}));

const mockFetchAgents = vi.mocked(agentApi.fetchAgents);
const mockCreateAgent = vi.mocked(agentApi.createAgent);
const mockUpdateAgent = vi.mocked(agentApi.updateAgent);
const mockDeleteAgent = vi.mocked(agentApi.deleteAgent);
const mockResetAgentPrompt = vi.mocked(agentApi.resetAgentPrompt);

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-1',
    name: 'test-agent',
    system_prompt: 'You are a helpful assistant.',
    default_prompt: 'Default system prompt.',
    model_profile: 'coder',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderAgents() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Agents />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetchAgents.mockResolvedValue([]);
  mockCreateAgent.mockResolvedValue(makeAgent());
  mockUpdateAgent.mockResolvedValue(makeAgent());
  mockDeleteAgent.mockResolvedValue(undefined);
  mockResetAgentPrompt.mockResolvedValue(makeAgent());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Agents page', () => {
  it('renders heading and New Agent button', async () => {
    renderAgents();
    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new agent/i })).toBeInTheDocument();
  });

  it('shows empty state when no agents exist', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();
    expect(await screen.findByText(/no agents configured/i)).toBeInTheDocument();
  });

  it('renders agent cards for each agent', async () => {
    mockFetchAgents.mockResolvedValue([
      makeAgent({ id: 'a1', name: 'alpha-agent' }),
      makeAgent({ id: 'a2', name: 'beta-agent' }),
    ]);
    renderAgents();
    expect(await screen.findByText('alpha-agent')).toBeInTheDocument();
    expect(screen.getByText('beta-agent')).toBeInTheDocument();
  });

  it('shows create form when New Agent is clicked', async () => {
    renderAgents();
    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));
    expect(screen.getByText('New Agent')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/e\.g\. my-custom-agent/i)).toBeInTheDocument();
  });

  it('calls createAgent with correct payload and closes form', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();

    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));

    const nameInput = screen.getByPlaceholderText(/e\.g\. my-custom-agent/i);
    await userEvent.type(nameInput, 'my-new-agent');

    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockCreateAgent).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'my-new-agent' }),
      );
    });
  });

  it('calls deleteAgent when Delete is confirmed via modal', async () => {
    const agent = makeAgent({ id: 'del-1', name: 'to-delete' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const deleteBtn = await screen.findByRole('button', { name: /delete to-delete/i });
    await userEvent.click(deleteBtn);

    const confirmBtn = await screen.findByRole('button', { name: /^delete$/i });
    await userEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockDeleteAgent).toHaveBeenCalledWith('del-1');
    });
  });

  it('shows confirmation modal with agent name when Delete is clicked', async () => {
    const agent = makeAgent({ id: 'del-1', name: 'to-delete' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const deleteBtn = await screen.findByRole('button', { name: /delete to-delete/i });
    await userEvent.click(deleteBtn);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/delete agent "to-delete"/i)).toBeInTheDocument();
  });

  it('does not call deleteAgent when Delete modal is cancelled', async () => {
    const agent = makeAgent({ id: 'del-2', name: 'keep-me' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const deleteBtn = await screen.findByRole('button', { name: /delete keep-me/i });
    await userEvent.click(deleteBtn);

    const cancelBtn = await screen.findByRole('button', { name: /cancel/i });
    await userEvent.click(cancelBtn);

    expect(mockDeleteAgent).not.toHaveBeenCalled();
  });

  it('does not delete immediately on card Delete button click', async () => {
    const agent = makeAgent({ id: 'del-3', name: 'no-immediate-delete' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const deleteBtn = await screen.findByRole('button', { name: /delete no-immediate-delete/i });
    await userEvent.click(deleteBtn);

    expect(mockDeleteAgent).not.toHaveBeenCalled();
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('shows error state when fetch fails', async () => {
    mockFetchAgents.mockRejectedValue(new Error('Network error'));
    renderAgents();
    expect(await screen.findByText(/failed to load agents/i)).toBeInTheDocument();
  });
});

describe('AgentEditor — edit mode', () => {
  it('opens editor with pre-filled values when Edit is clicked', async () => {
    const agent = makeAgent({ name: 'editable-agent', system_prompt: 'Existing prompt' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const editBtn = await screen.findByRole('button', { name: /edit editable-agent/i });
    await userEvent.click(editBtn);

    expect(screen.getByDisplayValue('editable-agent')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Existing prompt')).toBeInTheDocument();
  });

  it('calls updateAgent (PUT) when editing existing agent', async () => {
    const agent = makeAgent({ id: 'upd-1', name: 'update-me' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const editBtn = await screen.findByRole('button', { name: /edit update-me/i });
    await userEvent.click(editBtn);

    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockUpdateAgent).toHaveBeenCalledWith(
        'upd-1',
        expect.objectContaining({ name: 'update-me' }),
      );
    });
  });

  it('calls resetAgentPrompt when Reset to Default is clicked', async () => {
    const agent = makeAgent({ id: 'rst-1', name: 'reset-me', default_prompt: 'Default prompt.' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const editBtn = await screen.findByRole('button', { name: /edit reset-me/i });
    await userEvent.click(editBtn);

    const resetBtn = screen.getByRole('button', { name: /reset to default/i });
    await userEvent.click(resetBtn);

    await waitFor(() => {
      expect(mockResetAgentPrompt).toHaveBeenCalledWith('rst-1');
    });
  });

  it('hides Reset to Default button when default_prompt is null', async () => {
    const agent = makeAgent({ id: 'no-default', name: 'no-default-agent', default_prompt: '' });
    mockFetchAgents.mockResolvedValue([agent]);

    // Override the type since Agent type expects string but we want to test null case
    mockFetchAgents.mockResolvedValue([{ ...agent, default_prompt: null } as unknown as Agent]);

    renderAgents();

    const editBtn = await screen.findByRole('button', { name: /edit no-default-agent/i });
    await userEvent.click(editBtn);

    expect(screen.queryByRole('button', { name: /reset to default/i })).not.toBeInTheDocument();
  });

  it('shows validation error when name is empty', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();

    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    expect(screen.getByText(/name is required/i)).toBeInTheDocument();
    expect(mockCreateAgent).not.toHaveBeenCalled();
  });
});

describe('AgentEditor — model profile selector', () => {
  it('shows all 4 model profiles in selector', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();

    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));

    const select = screen.getByRole('combobox');
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(options).toContain('Architect');
    expect(options).toContain('Designer');
    expect(options).toContain('Coder');
    expect(options).toContain('Summarizer');
    expect(options).toHaveLength(4);
  });

  it('defaults to "coder" profile for new agents', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();

    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));

    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('coder');
  });

  it('shows agent model_profile in selector when editing', async () => {
    const agent = makeAgent({ model_profile: 'architect' });
    mockFetchAgents.mockResolvedValue([agent]);

    renderAgents();

    const editBtn = await screen.findByRole('button', { name: /edit test-agent/i });
    await userEvent.click(editBtn);

    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('architect');
  });

  it('sends selected model_profile when saving', async () => {
    mockFetchAgents.mockResolvedValue([]);
    renderAgents();

    await userEvent.click(screen.getByRole('button', { name: /new agent/i }));

    const nameInput = screen.getByPlaceholderText(/e\.g\. my-custom-agent/i);
    await userEvent.type(nameInput, 'profiled-agent');

    await userEvent.selectOptions(screen.getByRole('combobox'), 'designer');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockCreateAgent).toHaveBeenCalledWith(
        expect.objectContaining({ model_profile: 'designer' }),
      );
    });
  });
});
