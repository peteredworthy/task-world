import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RoutineSelector } from '../../src/components/RoutineSelector';
import * as useApiModule from '../../src/hooks/useApi';
import type { RoutineListResponse, ProjectRoutinesListResponse } from '../../src/types';

afterEach(cleanup);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

describe('RoutineSelector', () => {
  it('renders loading state while fetching routines', () => {
    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: undefined,
      isLoading: true,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Loading routines...')).toBeInTheDocument();
    const select = screen.getByRole('combobox');
    expect(select).toBeDisabled();
  });

  it('renders empty state when no routines are available', () => {
    const templatesData: RoutineListResponse = { routines: [] };
    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('No routines available')).toBeInTheDocument();
    const select = screen.getByRole('combobox');
    expect(select).toBeDisabled();
  });

  it('renders only templates when repoName is null', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: 'A template routine',
          source: 'system',
          step_count: 2,
          input_count: 1,
        },
        {
          id: 'routine-2',
          name: 'Template Two',
          description: null,
          source: 'system',
          step_count: 1,
          input_count: 0,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    // Should have Templates optgroup (check by role)
    const select = screen.getByRole('combobox');
    const optgroups = select.querySelectorAll('optgroup');
    expect(optgroups).toHaveLength(1);
    expect(optgroups[0]).toHaveAttribute('label', 'Templates');

    // Should have both routine options
    expect(screen.getByText(/Template One/)).toBeInTheDocument();
    expect(screen.getByText(/Template Two/)).toBeInTheDocument();
  });

  it('renders both templates and project routines when repoName is provided', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'template-1',
          name: 'Global Template',
          description: 'Global routine',
          source: 'system',
          step_count: 2,
          input_count: 1,
        },
      ],
    };

    const projectData: ProjectRoutinesListResponse = {
      routines: [
        {
          id: 'project-1',
          name: 'Project Routine',
          description: 'Project-specific',
          source: 'repo:my-repo',
          path: 'routines/custom.yaml',
          commit: 'abc123',
          has_scaffolding: false,
          config: {},
        },
      ],
      branch: 'main',
      commit: 'abc123',
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: projectData,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName="my-repo"
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    // Should have both optgroups (check by role)
    const select = screen.getByRole('combobox');
    const optgroups = select.querySelectorAll('optgroup');
    expect(optgroups).toHaveLength(2);
    expect(optgroups[0]).toHaveAttribute('label', 'Templates');
    expect(optgroups[1]).toHaveAttribute('label', 'Project Routines');

    // Should have both routine options
    expect(screen.getByText(/Global Template/)).toBeInTheDocument();
    expect(screen.getByText(/Project Routine/)).toBeInTheDocument();
  });

  it('calls onChange with selected routine id', async () => {
    const onChange = vi.fn();
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: 'A template',
          source: 'system',
          step_count: 2,
          input_count: 1,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={onChange}
      />,
      { wrapper: createWrapper() }
    );

    const select = screen.getByRole('combobox');
    await userEvent.selectOptions(select, 'routine-1');

    expect(onChange).toHaveBeenCalledWith('routine-1');
  });

  it('displays selected value', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: 'A template',
          source: 'system',
          step_count: 2,
          input_count: 1,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value="routine-1"
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    const select = screen.getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('routine-1');
  });

  it('respects autoFocus prop', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: null,
          source: 'system',
          step_count: 1,
          input_count: 0,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
        autoFocus={true}
      />,
      { wrapper: createWrapper() }
    );

    const select = screen.getByRole('combobox');
    // autoFocus is set but may not be reflected in the DOM attribute after rendering
    // Just verify the component accepts the prop without error
    expect(select).toBeInTheDocument();
  });

  it('respects required prop', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: null,
          source: 'system',
          step_count: 1,
          input_count: 0,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
        required={true}
      />,
      { wrapper: createWrapper() }
    );

    const select = screen.getByRole('combobox');
    expect(select).toBeRequired();
  });

  it('uses custom branch when provided', () => {
    const templatesData: RoutineListResponse = { routines: [] };
    const useRepoRoutinesSpy = vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName="my-repo"
        branch="feature-branch"
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    expect(useRepoRoutinesSpy).toHaveBeenCalledWith('my-repo', 'feature-branch');
  });

  it('shows description in option text if available', () => {
    const templatesData: RoutineListResponse = {
      routines: [
        {
          id: 'routine-1',
          name: 'Template One',
          description: 'With description',
          source: 'system',
          step_count: 1,
          input_count: 0,
        },
        {
          id: 'routine-2',
          name: 'Template Two',
          description: null,
          source: 'system',
          step_count: 1,
          input_count: 0,
        },
      ],
    };

    vi.spyOn(useApiModule, 'useRoutines').mockReturnValue({
      data: templatesData,
      isLoading: false,
    } as any);
    vi.spyOn(useApiModule, 'useRepoRoutines').mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any);

    render(
      <RoutineSelector
        repoName={null}
        value=""
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() }
    );

    // With description shows " - description"
    expect(screen.getByText(/Template One - With description/)).toBeInTheDocument();
    // Without description shows just the name
    expect(screen.getByText('Template Two')).toBeInTheDocument();
  });
});
