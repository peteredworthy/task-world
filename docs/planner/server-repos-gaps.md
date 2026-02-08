# Server-Managed Repos Implementation Gaps

This document details the gaps between the plan in `server-repos-plan.md` and what has been implemented.

## Summary

| Phase | Status | Completion |
|-------|--------|------------|
| 1.1 Configuration | **Complete** | 100% |
| 1.2 Repo Discovery | **Complete** | 100% |
| 1.3 API Endpoints | **Complete** | 100% |
| 1.4-1.5 Replace project_id | **Complete** | 100% |
| 2.1-2.2 Branch Selection UI | **Not Started** | 0% |
| 3.1-3.3 Project Routine Discovery | **Complete** | 100% |
| 4.1-4.3 Scaffolding | **Partial** | 70% |
| 5.1-5.4 Commit Tracking | **Mostly Complete** | 80% |
| 6.1-6.3 Worktree Directory | **Partial** | 50% |
| 7.1-7.2 CLI Updates | **Complete** | 100% |
| 8.1-8.2 MCP Updates | **Complete** | 100% |
| 9.1-9.4 UI Updates | **Partial** | 30% |

---

## Skipped Test Inventory

14 tests are currently skipped. 8 are environment-dependent or placeholder stubs; 6 represent real implementation gaps.

| Group | Count | Reason | Actionable? |
|-------|-------|--------|-------------|
| Branch/worktree ops (integration) | 5 | Worktree creation not wired into API start_run flow | **Yes** |
| Idea-to-plan E2E | 5 | Phase 9 feature not implemented (placeholder stubs) | No – future work |
| OpenHands Docker negative paths | 3 | Tools present in dev env; tests only run when absent | No – by design |
| Server restart recovery | 1 | Incomplete test that can never pass | **Yes – delete** |

### Branch/worktree ops – root cause

`WorkflowService.start_run()` has a comment at line 264:
> "Note: worktree creation is now handled by the caller (API layer) who has access to the repos_dir configuration"

But the API layer never implemented it. The call chain is:

```
POST /api/runs/{id}/start
  → executor.start_run_with_agent(run_id, service)
    → service.start_run(run_id)        # sets ACTIVE, no worktree
    → (spawn agent if managed)         # needs worktree_path already set
```

`WorktreeManager` exists and works (22 passing tests in `test_worktree.py`), but nobody calls `WorktreeManager.create()` during run start. The `WorkflowService.__init__` accepts `worktree_manager: WorktreeManager | None = None`, but `deps.py:get_workflow_service` never provides one. The executor also doesn't create one.

**Fix location:** `AgentExecutor.start_run_with_agent()` – after `service.start_run()`, before agent spawn. The executor already has `self._global_config` with `paths.get_repos_path()` and `paths.get_worktrees_path()`.

**Required changes:**
1. `AgentExecutor.start_run_with_agent()` – create `WorktreeManager(repos_dir / run.repo_name, worktrees_dir)` and call `.create(run.id, run.source_branch)` when `run.worktree_enabled` is True
2. `WorkflowService` – add `set_worktree_path(run_id, path)` method so executor can persist the path
3. `create_app()` – accept optional `global_config: GlobalConfig` parameter so tests can inject custom paths

**Test fixture changes:**
- `test_api_branch_ops.py:client_with_repo` – set up `tmp_path/repos/project` as repo, inject `GlobalConfig(paths=PathsConfig(repos_dir=..., worktrees_dir=...))` into `create_app`
- `_create_and_start_run` – use `repo_name=project_path.name` (directory name) instead of `str(project_path)` (full path)
- `test_branch_ops.py:TestWorktreeCreationOnStart` – remove entirely; these tested service-level creation which no longer applies. API-level tests cover the same behavior.

### Server restart recovery – root cause

`test_failure_recovery.py::test_recovery_from_server_restart` kills the server process via SIGTERM but never restarts it. The test body ends with a comment: "Server would need to be restarted here with same database. This is complex in a pytest fixture context." The other 5 tests in the file pass and cover persistence adequately. **Delete this test.**

---

## Detailed Gap Analysis

### Phase 2: Branch Selection UI (NOT IMPLEMENTED)

**Plan specified:**
- `ui/src/components/BranchSelector.tsx` - Glob pattern-filtered branch input
- Behavior: Text input with debounced matching, 100+ threshold messaging
- Show dropdown only when count <= 100, otherwise show "refine pattern" message

**Current state:**
- **`BranchSelector.tsx` does not exist**
- Branch is entered as free text in `CreateRunModal.tsx` (line 311-318)
- No glob pattern matching in UI
- No branch count checking
- No 100+ threshold messaging

**Files to create:**
- `ui/src/components/BranchSelector.tsx`

**Files to modify:**
- `ui/src/components/dashboard/CreateRunModal.tsx` - Replace free text with BranchSelector

---

### Phase 4: Scaffolding (PARTIALLY IMPLEMENTED)

**Plan specified:**
- `src/orchestrator/scaffolding/` module with copier logic
- Call `_copy_scaffolding()` in `workflow/service.py` `start_run()`
- Move `routines/idea-to-plan.yaml` to `routines/idea-to-plan/routine.yaml` with `scaffolding/` folder

**Current state:**
- **Scaffolding module exists** (`src/orchestrator/scaffolding/`) with:
  - `copier.py` - `copy_scaffolding()` function
  - `models.py` - `ScaffoldingResult` model
  - `errors.py` - `ScaffoldingError`

**Gaps:**
1. **`copy_scaffolding()` is not called from `workflow/service.py`**
   - The plan says to call it in `start_run()` after worktree creation
   - Currently not integrated into the workflow

2. **`idea-to-plan` routine not restructured**
   - Still exists as flat file: `routines/idea-to-plan.yaml`
   - Plan called for: `routines/idea-to-plan/routine.yaml` + `scaffolding/` folder
   - No scaffolding templates created

**Files to modify:**
- `src/orchestrator/workflow/service.py` - Add scaffolding copy call
- `routines/idea-to-plan.yaml` - Move to directory structure

---

### Phase 5: Commit Tracking (MOSTLY IMPLEMENTED)

**Plan specified:**
- `start_commit` and `end_commit` fields on `Attempt` model
- Capture `start_commit` in `start_task()`
- Capture `end_commit` in `submit_for_verification()`
- Builder prompt enhancement: instruct to commit before submit
- Verifier checkout in Docker agent: checkout `end_commit` before starting

**Current state:**
- **Fields exist** in `state/models.py`:
  - `start_commit: str | None = None`
  - `end_commit: str | None = None`
- **`get_head_commit()` utility exists** in `git/utils.py`
- Fields are persisted in DB (`db/models.py`, `db/repositories.py`)
- **Commits ARE captured** in `workflow/service.py`:
  - `start_commit` set in `start_task()` (line 388)
  - `end_commit` set in `submit_for_verification()` (line 441)

**Gaps:**
1. **Builder prompt not enhanced**
   - Plan says to add: "Before submitting for verification: 1. Stage all relevant changes... 2. Commit with descriptive message... 3. Then call submit"
   - Current `workflow/prompts.py` does not include git commit instructions

2. **Verifier checkout not implemented**
   - Plan says: "Before starting verifier in container: if attempt.end_commit: checkout specific commit"
   - `agents/openhands_docker.py` does not implement checkout of `end_commit`

**Files to modify:**
- `src/orchestrator/workflow/prompts.py` - Add git commit instructions to builder prompt
- `src/orchestrator/agents/openhands_docker.py` - Add verifier checkout logic

---

### Phase 6: Worktree Directory (PARTIALLY IMPLEMENTED)

**Plan specified:**
- `WorktreeManager` takes `worktree_dir` from settings (required, no default)
- Worktrees created in `{project-root}/worktrees/run-{run_id}/`
- `workflow/service.py` uses `_get_worktree_manager()` to create manager

**Current state:**
- **`WorktreeManager` exists** with correct signature (takes `repo_path` and `worktree_dir`)
- **Settings include `worktrees_dir`** in `GlobalConfig.paths`
- `WorktreeManager` is thoroughly tested (22 passing tests)

**Gaps:**

1. **Worktree creation not wired into start_run flow** (see detailed analysis above)
   - `WorkflowService` accepts `worktree_manager` but `deps.py` never provides one
   - `AgentExecutor` has `global_config` but doesn't create worktrees
   - 5 tests skipped: 2 in `test_branch_ops.py`, 3 in `test_api_branch_ops.py`

2. **Worktree cleanup not wired for API-served requests**
   - `WorkflowService.cancel_run()` and `complete_verification()` call `handle_run_completion(run, self._worktree_manager)` only if `self._worktree_manager is not None`
   - `deps.py:get_workflow_service` doesn't inject a worktree manager
   - Cleanup only works if the executor's internally-created service has one (it doesn't)
   - Worktrees accumulate without cleanup

3. **`create_app()` doesn't accept a custom `GlobalConfig`**
   - Tests cannot inject custom `repos_dir` / `worktrees_dir` paths
   - Need to add optional `global_config` parameter

**Files to modify:**
- `src/orchestrator/agents/executor.py` - Create worktree in `start_run_with_agent()`
- `src/orchestrator/workflow/service.py` - Add `set_worktree_path()` method
- `src/orchestrator/api/app.py` - Add `global_config` parameter to `create_app()`
- `src/orchestrator/api/deps.py` - Wire worktree manager into service for cleanup (future)

---

### Phase 9: UI Updates (PARTIALLY IMPLEMENTED)

**Plan specified:**
- `ui/src/pages/Repos.tsx` - Repository list page
- `ui/src/components/RoutineSelector.tsx` - Grouped routine selector (Templates vs Project)
- Enhanced run creation flow: Repo dropdown → Branch selector → Routine selector
- Remove all `project_id` references (use `repo_name`)

**Current state:**
- **`project_id` → `repo_name` migration complete** in:
  - `ui/src/types/runs.ts`
  - `ui/src/api/client.ts`
  - `ui/src/hooks/useApi.ts`
  - `ui/src/pages/Dashboard.tsx`
  - `ui/src/components/dashboard/RunCard.tsx`
  - `ui/src/lib/activity.test.ts`

**Gaps:**
1. **`Repos.tsx` page does not exist**
   - Plan specified: List repos, show default branch, link to create run

2. **`RoutineSelector.tsx` does not exist**
   - Plan specified: Grouped list showing "Templates" vs "Project Routines"

3. **`CreateRunModal.tsx` not fully updated**
   - Still uses free text "Target Project" field (not repo dropdown)
   - Still uses `projectId` as internal state variable name
   - No repo selection dropdown using `useRepos()` hook
   - No branch selector with glob patterns
   - No project routine discovery integration

**Files to create:**
- `ui/src/pages/Repos.tsx`
- `ui/src/components/BranchSelector.tsx`
- `ui/src/components/RoutineSelector.tsx`

**Files to modify:**
- `ui/src/components/dashboard/CreateRunModal.tsx` - Complete rewrite of creation flow

---

## Priority Ordering

### High Priority (Core functionality gaps)

1. **Worktree creation in API layer** (Phase 6)
   - Blocking: Cannot start runs that need worktrees
   - 5 tests currently skipped
   - Fix is well-understood (see detailed analysis above)

2. **Scaffolding integration** (Phase 4)
   - Call `copy_scaffolding()` from workflow service
   - Enables project routines with templates

3. **Builder prompt git instructions** (Phase 5)
   - Critical for correctness: verifier needs committed changes

### Medium Priority (UX improvements)

4. **CreateRunModal redesign** (Phase 9)
   - Replace free text with repo dropdown + branch selector
   - Integrate with existing `useRepos()` and `useBranches()` hooks

5. **BranchSelector component** (Phase 2)
   - Glob pattern matching UI
   - 100+ threshold messaging

6. **RoutineSelector component** (Phase 9)
   - Grouped Templates vs Project Routines

### Low Priority (Polish)

7. **Repos.tsx page** (Phase 9)
   - Standalone repo browsing

8. **idea-to-plan restructuring** (Phase 4)
   - Move to directory-based format with scaffolding

9. **Verifier checkout for Docker agent** (Phase 5)
   - Only needed for Docker-based verifiers

10. **Worktree cleanup wiring** (Phase 6)
    - Wire `WorktreeManager` into service via `deps.py` for cancel/complete cleanup
    - Low priority because worktrees are small and can be manually cleaned

---

## Estimated Effort

| Gap | Effort | Notes |
|-----|--------|-------|
| Worktree in API | M | Executor + service + app factory + test fixtures |
| Scaffolding integration | S | Single function call + tests |
| Builder prompt | S | Add text to prompts.py |
| CreateRunModal redesign | L | Major component rewrite |
| BranchSelector | M | New component with debounce logic |
| RoutineSelector | M | New component with grouping |
| Repos.tsx | M | New page with listing |
| idea-to-plan restructure | S | Move files, update yaml |
| Verifier checkout | S | Small code change in docker agent |
| Worktree cleanup wiring | S | Pass manager through deps.py |

**Legend:** S = Small (< 1 hour), M = Medium (1-4 hours), L = Large (4+ hours)
