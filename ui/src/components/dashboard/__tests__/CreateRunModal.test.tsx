import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CreateRunModal } from '../CreateRunModal';
import { CreateRunContext } from '../../../context/createRunContextValue';
import * as useApiModule from '../../../hooks/useApi';

vi.mock('../../../hooks/useApi', () => ({
  useRepos: vi.fn(),
  useAgentRunners: vi.fn(),
  useCreateRun: vi.fn(),
  useStartRun: vi.fn(),
  useRoutine: vi.fn(),
}));

vi.mock('../../../components/BranchSelector', () => ({
  BranchSelector: () => <div data-testid="branch-selector" />,
}));

vi.mock('../../../components/RoutineSelector', () => ({
  RoutineSelector: () => <div data-testid="routine-selector" />,
}));

vi.mock('../../../components/RoutineValidatorModal', () => ({
  RoutineValidatorModal: () => null,
}));

vi.mock('../../../hooks/useFocusTrap', () => ({
  useFocusTrap: vi.fn(),
}));

const mockUseCreateRun = vi.mocked(useApiModule.useCreateRun);
const mockUseStartRun = vi.mocked(useApiModule.useStartRun);
const mockUseRepos = vi.mocked(useApiModule.useRepos);
const mockUseAgentRunners = vi.mocked(useApiModule.useAgentRunners);
const mockUseRoutine = vi.mocked(useApiModule.useRoutine);

const createRunContextValue = {
  isOpen: true,
  open: vi.fn(),
  close: vi.fn(),
  preSelectedRoutine: null,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderModal(open = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <CreateRunContext.Provider value={createRunContextValue}>
        <CreateRunModal open={open} onClose={vi.fn()} />
      </CreateRunContext.Provider>
    </QueryClientProvider>,
  );
}

function setupDefaultMocks() {
  mockUseRepos.mockReturnValue({ data: { repos: [] }, isLoading: false } as any);
  mockUseAgentRunners.mockReturnValue({ data: [], isLoading: false } as any);
  mockUseStartRun.mockReturnValue({ isPending: false, mutateAsync: vi.fn() } as any);
  mockUseRoutine.mockReturnValue({ data: null } as any);
}

describe('CreateRunModal — model validation error display', () => {
  it('shows a generic error message when createRun fails with no specific message', () => {
    setupDefaultMocks();
    mockUseCreateRun.mockReturnValue({
      isError: true,
      error: null,
      isPending: false,
      mutateAsync: vi.fn(),
    } as any);

    renderModal();

    expect(screen.getByText('Failed to create run. Check your inputs.')).toBeInTheDocument();
  });

  it('shows the specific API error message when model validation fails', () => {
    setupDefaultMocks();
    mockUseCreateRun.mockReturnValue({
      isError: true,
      error: new Error(
        "Model 'gpt-5.2-codex' is not available for the selected Codex runner. " +
          'Available models: gpt-5.3-codex. ' +
          'Use GET /api/agent-runners to discover available models.',
      ),
      isPending: false,
      mutateAsync: vi.fn(),
    } as any);

    renderModal();

    expect(
      screen.getByText(/gpt-5\.2-codex.*is not available/),
    ).toBeInTheDocument();
    expect(screen.getByText(/gpt-5\.3-codex/)).toBeInTheDocument();
  });

  it('does not show any error message when createRun has not failed', () => {
    setupDefaultMocks();
    mockUseCreateRun.mockReturnValue({
      isError: false,
      error: null,
      isPending: false,
      mutateAsync: vi.fn(),
    } as any);

    renderModal();

    expect(screen.queryByText(/Failed to create run/)).not.toBeInTheDocument();
    expect(screen.queryByText(/is not available/)).not.toBeInTheDocument();
  });
});
