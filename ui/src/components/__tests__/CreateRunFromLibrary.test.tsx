import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RoutineSelector } from '../RoutineSelector';
import { groupRoutines } from '../routineGrouping';
import { CreateRunModal } from '../dashboard/CreateRunModal';
import { CreateRunContext } from '../../context/createRunContextValue';
import {
  useRepos,
  useAgentRunners,
  useCreateRun,
  useStartRun,
  useRoutine,
  useRoutines,
  useRepoRoutines,
  useBranchCount,
  useBranches,
  useValidateRoutine,
  useGlobalConfig,
} from '../../hooks/useApi';
import type { RoutineSummary } from '../../types/routines';
import type { ProjectRoutineResponse } from '../../types/repos';

vi.mock('../../hooks/useApi', () => ({
  useRepos: vi.fn(),
  useAgentRunners: vi.fn(),
  useCreateRun: vi.fn(),
  useStartRun: vi.fn(),
  useRoutine: vi.fn(),
  useRoutines: vi.fn(),
  useRepoRoutines: vi.fn(),
  useBranchCount: vi.fn(),
  useBranches: vi.fn(),
  useValidateRoutine: vi.fn(),
  useGlobalConfig: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ── helpers ──────────────────────────────────────────────────────────────────

function makeTemplate(id: string, name: string): RoutineSummary {
  return { id, name, description: null, source: 'local', step_count: 1, input_count: 0, is_archived: false };
}

function makeProjectRoutine(id: string, name: string): ProjectRoutineResponse {
  return { id, name, description: null, source: 'project', path: `.routines/${id}.yaml`, commit: 'abc', has_scaffolding: false, config: {} };
}

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

// ── groupRoutines unit tests ──────────────────────────────────────────────────

describe('groupRoutines', () => {
  it('excludes a template whose id also appears in project routines', () => {
    const templates = [makeTemplate('shared-id', 'Shared'), makeTemplate('only-template', 'Only Template')];
    const projects = [makeProjectRoutine('shared-id', 'Shared (project)')];

    const { templates: t, projectRoutines: p } = groupRoutines(templates, projects);

    expect(t).toHaveLength(1);
    expect(t[0].id).toBe('only-template');
    expect(p).toHaveLength(1);
    expect(p[0].id).toBe('shared-id');
  });

  it('drops templates with blank ids', () => {
    const templates = [makeTemplate('', 'Blank ID'), makeTemplate('valid', 'Valid')];

    const { templates: t } = groupRoutines(templates, []);

    expect(t).toHaveLength(1);
    expect(t[0].id).toBe('valid');
  });

  it('drops project routines with blank ids', () => {
    const projects = [makeProjectRoutine('', 'Blank'), makeProjectRoutine('proj', 'Project')];

    const { projectRoutines: p } = groupRoutines([], projects);

    expect(p).toHaveLength(1);
    expect(p[0].id).toBe('proj');
  });

  it('returns all entries when there is no overlap', () => {
    const templates = [makeTemplate('t1', 'T1'), makeTemplate('t2', 'T2')];
    const projects = [makeProjectRoutine('p1', 'P1')];

    const { templates: t, projectRoutines: p } = groupRoutines(templates, projects);

    expect(t).toHaveLength(2);
    expect(p).toHaveLength(1);
  });
});

// ── RoutineSelector – no duplicates or blank options ─────────────────────────

describe('RoutineSelector', () => {
  function renderSelector(value = '') {
    vi.mocked(useRoutines).mockReturnValue({
      data: {
        routines: [
          makeTemplate('tmpl-only', 'Template Only'),
          makeTemplate('shared', 'Shared Routine'),
        ],
      },
      isLoading: false,
    } as ReturnType<typeof useRoutines>);

    vi.mocked(useRepoRoutines).mockReturnValue({
      data: {
        routines: [makeProjectRoutine('shared', 'Shared Routine'), makeProjectRoutine('proj-only', 'Project Only')],
        branch: 'main',
        commit: 'abc',
      },
      isLoading: false,
    } as ReturnType<typeof useRepoRoutines>);

    render(
      <QueryClientProvider client={makeQueryClient()}>
        <RoutineSelector
          repoName="my-repo"
          branch="main"
          value={value}
          onChange={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  it('renders each routine id exactly once even when shared between templates and project routines', () => {
    renderSelector();
    const options = screen.getAllByRole('option');
    const ids = options.map(o => (o as HTMLOptionElement).value).filter(v => v !== '');
    const unique = new Set(ids);
    expect(ids.length).toBe(unique.size);
  });

  it('renders no option with an empty value other than the placeholder', () => {
    renderSelector();
    const options = screen.getAllByRole('option');
    const blanks = options.filter(o => (o as HTMLOptionElement).value === '');
    // Only the placeholder "Select a routine..." should have value=""
    expect(blanks).toHaveLength(1);
    expect(blanks[0]).toHaveTextContent('Select a routine...');
  });

  it('selects the correct routine when value matches a template id', () => {
    renderSelector('tmpl-only');
    const select = screen.getByRole('combobox');
    expect(select).toHaveValue('tmpl-only');
  });
});

// ── CreateRunModal – pre-selected routine preservation ───────────────────────

describe('CreateRunModal – pre-selected routine from Routine Library', () => {
  function setupModalMocks() {
    vi.mocked(useRepos).mockReturnValue({
      data: { repos: [{ name: 'my-repo', path: '/my/repo', default_branch: 'main' }] },
      isLoading: false,
    } as ReturnType<typeof useRepos>);

    vi.mocked(useAgentRunners).mockReturnValue({
      data: [],
      isLoading: false,
    } as ReturnType<typeof useAgentRunners>);

    vi.mocked(useCreateRun).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useCreateRun>);

    vi.mocked(useStartRun).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      variables: undefined,
    } as unknown as ReturnType<typeof useStartRun>);

    vi.mocked(useRoutine).mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useRoutine>);

    vi.mocked(useRoutines).mockReturnValue({
      data: { routines: [makeTemplate('library-routine', 'Library Routine')] },
      isLoading: false,
    } as ReturnType<typeof useRoutines>);

    vi.mocked(useRepoRoutines).mockReturnValue({
      data: { routines: [], branch: 'main', commit: 'abc' },
      isLoading: false,
    } as ReturnType<typeof useRepoRoutines>);

    vi.mocked(useBranchCount).mockReturnValue({
      data: { count: 1, pattern: '*' },
    } as ReturnType<typeof useBranchCount>);

    vi.mocked(useBranches).mockReturnValue({
      data: { branches: [{ name: 'main', is_remote: false, commit: 'abc' }], total: 1, truncated: false },
      isLoading: false,
    } as ReturnType<typeof useBranches>);

    vi.mocked(useValidateRoutine).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useValidateRoutine>);

    vi.mocked(useGlobalConfig).mockReturnValue({
      data: {
        dashboard_refresh_interval_seconds: 5,
        dashboard_max_recent_runs: 50,
        default_execution_mode: 'graph',
        agents_openhands_url: null,
        agents_default_type: null,
      },
    } as ReturnType<typeof useGlobalConfig>);
  }

  function renderModal(preSelectedRoutine: string | null) {
    return render(
      <QueryClientProvider client={makeQueryClient()}>
        <CreateRunContext.Provider
          value={{ isOpen: true, open: vi.fn(), close: vi.fn(), preSelectedRoutine }}
        >
          <CreateRunModal open onClose={vi.fn()} />
        </CreateRunContext.Provider>
      </QueryClientProvider>,
    );
  }

  it('preserves the pre-selected routine when the user then picks a repo', async () => {
    setupModalMocks();
    const user = userEvent.setup();
    renderModal('library-routine');

    // Modal should show the repo select (not loading since mocks return data)
    const repoSelect = screen.getByRole('combobox');
    expect(repoSelect).toBeInTheDocument();

    // RoutineSelector is hidden until a repo is chosen
    expect(screen.queryByText('Library Routine')).not.toBeInTheDocument();

    // Pick a repo
    await user.selectOptions(repoSelect, 'my-repo');

    // Now both repo select and routine select are visible
    const allCombos = screen.getAllByRole('combobox');
    const routineSelect = allCombos.find(el =>
      Array.from(el.querySelectorAll('option')).some(
        o => (o as HTMLOptionElement).value === 'library-routine',
      ),
    );

    expect(routineSelect).toBeDefined();
    expect(routineSelect).toHaveValue('library-routine');
  });

  it('clears the routine when a project routine was active and the repo changes', async () => {
    setupModalMocks();

    // Patch useRepoRoutines to return a project routine for the initial repo
    vi.mocked(useRepoRoutines).mockReturnValue({
      data: { routines: [makeProjectRoutine('proj-routine', 'Project Routine')], branch: 'main', commit: 'abc' },
      isLoading: false,
    } as ReturnType<typeof useRepoRoutines>);

    // Also add a second repo to switch to
    vi.mocked(useRepos).mockReturnValue({
      data: {
        repos: [
          { name: 'repo-a', path: '/repo-a', default_branch: 'main' },
          { name: 'repo-b', path: '/repo-b', default_branch: 'main' },
        ],
      },
      isLoading: false,
    } as ReturnType<typeof useRepos>);

    const user = userEvent.setup();
    renderModal(null);

    // Select first repo
    const repoSelect = screen.getByRole('combobox');
    await user.selectOptions(repoSelect, 'repo-a');

    // Select the project routine
    const allCombos = screen.getAllByRole('combobox');
    const routineSelect = allCombos.find(el =>
      Array.from(el.querySelectorAll('option')).some(
        o => (o as HTMLOptionElement).value === 'proj-routine',
      ),
    );
    expect(routineSelect).toBeDefined();
    await user.selectOptions(routineSelect!, 'proj-routine');
    expect(routineSelect).toHaveValue('proj-routine');

    // Now switch repo – project routine should be cleared
    vi.mocked(useRepoRoutines).mockReturnValue({
      data: { routines: [], branch: 'main', commit: 'abc' },
      isLoading: false,
    } as ReturnType<typeof useRepoRoutines>);

    const repoSelectAfter = screen.getAllByRole('combobox')[0];
    await user.selectOptions(repoSelectAfter, 'repo-b');

    // Routine should have been cleared – value back to ''
    // Find by the template option which is unique to the routine selector (not the repo selector)
    const combosAfter = screen.getAllByRole('combobox');
    const routineSelectAfter = combosAfter.find(el =>
      Array.from(el.querySelectorAll('option')).some(
        o => (o as HTMLOptionElement).value === 'library-routine',
      ),
    );
    expect(routineSelectAfter).toBeDefined();
    expect(routineSelectAfter).toHaveValue('');
  });
});
