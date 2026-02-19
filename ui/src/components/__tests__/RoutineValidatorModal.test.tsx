import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ComponentProps } from 'react';
import { RoutineValidatorModal } from '../RoutineValidatorModal';
import { useValidateRoutine } from '../../hooks/useApi';

vi.mock('../../hooks/useApi', () => ({
  useValidateRoutine: vi.fn(),
}));

const mockUseValidateRoutine = vi.mocked(useValidateRoutine);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderModal(props?: Partial<ComponentProps<typeof RoutineValidatorModal>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RoutineValidatorModal
        isOpen
        onClose={vi.fn()}
        onCreateRun={vi.fn()}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe('RoutineValidatorModal', () => {
  it('shows validation error list with line numbers on invalid result', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      valid: false,
      errors: [
        { line: 7, message: 'missing required field: steps' },
        { line: 0, message: 'bad type for name' },
      ],
    });

    mockUseValidateRoutine.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as ReturnType<typeof useValidateRoutine>);

    const user = userEvent.setup();
    renderModal();

    await user.type(screen.getByPlaceholderText('Paste your routine YAML here...'), 'id: demo');
    await user.click(screen.getByRole('button', { name: 'Validate' }));

    expect(screen.getByText('Validation errors')).toBeInTheDocument();
    expect(screen.getByText('Line 7: missing required field: steps')).toBeInTheDocument();
    expect(screen.getByText('Line 1: bad type for name')).toBeInTheDocument();
  });

  it('shows "Create run from this routine" shortcut on valid result', async () => {
    const yaml = 'id: demo-routine\nname: Demo Routine\nsteps:\n  - id: step-1';
    const onCreateRun = vi.fn();
    const onClose = vi.fn();
    const mutateAsync = vi.fn().mockResolvedValue({
      valid: true,
      errors: [],
    });

    mockUseValidateRoutine.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as ReturnType<typeof useValidateRoutine>);

    const user = userEvent.setup();
    renderModal({ onCreateRun, onClose });

    await user.type(screen.getByPlaceholderText('Paste your routine YAML here...'), yaml);
    await user.click(screen.getByRole('button', { name: 'Validate' }));

    const shortcut = await screen.findByRole('button', { name: 'Create run from this routine' });
    expect(shortcut).toBeInTheDocument();

    await user.click(shortcut);

    expect(onCreateRun).toHaveBeenCalledTimes(1);
    expect(onCreateRun).toHaveBeenCalledWith(yaml);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
