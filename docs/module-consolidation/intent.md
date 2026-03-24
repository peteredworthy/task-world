# Intent: Module Consolidation

## Original Request

Implement all of the work described in the module consolidation intent document — consolidate 19 modules down to 9 [S-02/T-01/R1, S-03/T-01/R1, S-04/T-01/R1, S-05/T-01/R1, S-05/T-01/R2, S-06/T-01/R2, S-06/T-01/R3, S-07/T-01/R1, S-08/T-01/R1, S-09/T-01/R1], resolve anomalous couplings [S-00/T-01/R1, S-00/T-01/R2, S-00/T-01/R3, S-00/T-01/R4, S-00/T-02/R1, S-00/T-02/R2], delete dead code [S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4], and enforce explicit `__all__` interfaces [S-10/T-01/R1]. Critical emphasis: moves must be completed 100%, leaving behind no stubs, shims, or unconnected code [S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4, S-07/T-01/R2, S-08/T-01/R2, S-09/T-01/R2].

## Goal

Restructure `src/orchestrator/` from 19 loosely-bounded modules into 9 coherent modules [S-02/T-01/R1, S-03/T-01/R1, S-04/T-01/R1, S-05/T-01/R1, S-06/T-01/R2] with explicit public interfaces (`__all__`) [S-10/T-01/R1], resolving all cross-layer coupling violations [S-00/T-01/R1, S-00/T-01/R2, S-00/T-01/R3, S-00/T-01/R4, S-00/T-02/R1, S-00/T-02/R2], deleting all dead shims [S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4], and ensuring every import path is updated so no backward-compatibility stubs remain [S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4, S-07/T-01/R2, S-08/T-01/R2, S-09/T-01/R2, S-10/T-01/R1].

## Scope

### In Scope

- **Resolve 6 anomalous couplings (C1–C6)** — Fix cross-layer imports before moving any files: [S-00/T-01/R1, S-00/T-01/R2, S-00/T-01/R3, S-00/T-01/R4, S-00/T-02/R1, S-00/T-02/R2]
  - C1: Move `NudgerConfig` out of `runners/` into `config/models.py` [S-00/T-01/R1]
  - C2: Move `CommitInfo`, `FileStatus`, `ModifiedFile` from `review/models` into `git/` [S-00/T-01/R2]
  - C3: Move `ActionLog` from `runners/action_log` into `state/models.py` [S-00/T-01/R3]
  - C4: Move `EnvFileSpec` from `envfiles/models` into `config/models.py` [S-00/T-01/R4]
  - C5: Replace `api/schemas/runs.RecoverResponse` usage in `workflow/service.py` with a plain dataclass [S-00/T-02/R1]
  - C6: Replace direct `WorkflowService` import in `UserManagedAgent` with a protocol/callback [S-00/T-02/R2]

- **Delete dead code** — Remove `routers/` shim directory, `agent_detector.py`, `parsers/` shims, `openhands.py`/`openhands_docker.py`/`openhands_common.py`/`codex_server.py`/`codex_server_common.py` shims (all verified zero consumers) [S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4]

- **Absorb modules into target structure:** [S-02/T-01/R1, S-03/T-01/R1, S-04/T-01/R1, S-05/T-01/R1, S-05/T-01/R2, S-06/T-01/R2, S-06/T-01/R3]
  - `routines/` → `config/routines/` (routine discovery, loading, versioning) [S-03/T-01/R1, S-03/T-01/R2]
  - `cache/` + `review/` + `repos/` → `git/` (diff models, repo discovery, test runner, LRU cache) [S-02/T-01/R1, S-02/T-01/R2]
  - `artifacts/` → `workflow/artifacts/` (artifact registry) [S-04/T-01/R1, S-04/T-01/R2]
  - `metrics/` + `mcp/` → `api/` (cost metrics, MCP server) [S-05/T-01/R1, S-05/T-01/R2, S-05/T-01/R3]
  - `scaffolding/` + `agents/` (profiles) → `runners/` (workspace setup, agent persona CRUD) [S-06/T-01/R2, S-06/T-01/R3, S-06/T-01/R4]

- **Internal restructuring** — Reorganize internals of `workflow/`, `db/`, and `runners/` into sub-packages (engine/, events/, signals/, agent/ for workflow; orm/, access/, recovery/ for db; detection/, runtime/ for runners) [S-07/T-01/R1, S-08/T-01/R1, S-09/T-01/R1]

- **Explicit `__all__` on all 9 modules** — Every module's `__init__.py` declares `__all__` explicitly [S-10/T-01/R1]. External imports must come from module top-level, not sub-packages [S-10/T-01/R1].

- **Fix reverse dependency violations:** [S-10/T-01/R2, S-07/T-01/R3]
  - `runners/executor.py` importing `api/websocket.ConnectionManager` → define `BroadcastCallback` protocol [S-10/T-01/R2]
  - `runners` ↔ `workflow` circular coupling (`NoTaskReason`) → move to `workflow/` [S-07/T-01/R3]

- **Surface area reduction** — Move internal-only symbols out of public interfaces (e.g., `RunWorkflow` becomes private, `check_step_progression`/`check_run_completion` move behind `WorkflowService`, raw ORM models hidden behind repositories) [S-10/T-01/R3, S-10/T-01/R4]

- **Update ALL import paths** — Every file that imports a moved symbol must be updated [S-00/T-01/R1, S-00/T-01/R2, S-00/T-01/R3, S-00/T-01/R4, S-00/T-02/R1, S-00/T-02/R2, S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4, S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4, S-07/T-01/R2, S-08/T-01/R2, S-09/T-01/R2]. No `import X from old.path` left behind. No re-export shims [S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4].

- **All tests pass** — Backend unit tests, integration tests, frontend tests, TypeScript type check, ESLint, build all pass after each phase [S-00/T-02/R3, S-01/T-01/R5, S-02/T-01/R5, S-03/T-01/R4, S-04/T-01/R4, S-05/T-01/R5, S-06/T-01/R5, S-07/T-01/R4, S-08/T-01/R4, S-09/T-01/R3, S-10/T-01/R5].

### Out of Scope

- Functional changes to any module's behavior — this is purely structural [NO-REQ: structural-only constraint; violations would appear as test failures, not as a separate requirement]
- New features or API endpoint changes [NO-REQ: out of scope by definition; covered implicitly by the test-pass requirements]
- Database schema migrations (no ORM model changes, just file moves) [NO-REQ: structural file moves only; no migration files needed]
- Frontend code changes (unless import paths change in shared types) [NO-REQ: frontend unchanged unless import paths affect shared types, covered by S-10/T-01/R5 tests]
- RunService or ReviewService extraction (separate effort after consolidation stabilizes) [NO-REQ: explicitly deferred to a separate effort]
- Linting rule to enforce import discipline (future follow-up) [NO-REQ: future follow-up; enforcement is manual + code review in this effort]

## Definition of Complete

- [ ] All 6 anomalous couplings (C1–C6) resolved — no cross-layer imports remain [S-00/T-01/R1, S-00/T-01/R2, S-00/T-01/R3, S-00/T-01/R4, S-00/T-02/R1, S-00/T-02/R2]
- [ ] All dead code deleted — zero shim files exist (`routers/` dir, `agent_detector.py`, `parsers/` shims, backward-compat agent shims) [S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4]
- [ ] `routines/` absorbed into `config/routines/` — original `routines/` directory removed entirely [S-03/T-01/R1, S-03/T-01/R2]
- [ ] `cache/`, `review/`, `repos/` absorbed into `git/` — original directories removed entirely [S-02/T-01/R1, S-02/T-01/R2]
- [ ] `artifacts/` absorbed into `workflow/artifacts/` — original directory removed entirely [S-04/T-01/R1, S-04/T-01/R2]
- [ ] `metrics/`, `mcp/` absorbed into `api/` — original directories removed entirely [S-05/T-01/R1, S-05/T-01/R2, S-05/T-01/R3]
- [ ] `scaffolding/`, `agents/` (profiles) absorbed into `runners/` — original directories removed entirely [S-06/T-01/R2, S-06/T-01/R3, S-06/T-01/R4]
- [ ] `workflow/` internals restructured into engine/, events/, signals/, agent/ sub-packages [S-07/T-01/R1, S-07/T-01/R2]
- [ ] `db/` internals restructured into orm/, access/, recovery/ sub-packages [S-08/T-01/R1, S-08/T-01/R2]
- [ ] `runners/` internals restructured into detection/, runtime/ sub-packages [S-09/T-01/R1, S-09/T-01/R2]
- [ ] All 9 module `__init__.py` files declare explicit `__all__` [S-10/T-01/R1]
- [ ] Zero backward-compatibility shims, re-export stubs, or `# removed` comments in codebase [S-01/T-01/R1, S-01/T-01/R2, S-01/T-01/R3, S-01/T-01/R4, S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4, S-07/T-01/R2, S-08/T-01/R2, S-09/T-01/R2]
- [ ] Every import statement across the entire codebase uses the new canonical paths [S-02/T-01/R3, S-03/T-01/R3, S-04/T-01/R3, S-05/T-01/R4, S-06/T-01/R4, S-07/T-01/R2, S-08/T-01/R2, S-09/T-01/R2]
- [ ] No file imports from a sub-package of another module (only top-level module imports) [S-10/T-01/R1]
- [ ] All backend tests pass (`uv run pytest tests/`) [S-00/T-02/R3, S-01/T-01/R5, S-02/T-01/R5, S-03/T-01/R4, S-04/T-01/R4, S-05/T-01/R5, S-06/T-01/R5, S-07/T-01/R4, S-08/T-01/R4, S-09/T-01/R3, S-10/T-01/R5]
- [ ] All frontend tests pass (`cd ui && npx vitest run`) [S-10/T-01/R5]
- [ ] TypeScript type check clean, ESLint clean, frontend build passes [S-10/T-01/R5]
- [ ] `uv run pre-commit run --all-files` passes [S-10/T-01/R5]
