# Step 1: Delete Dead Code

Remove all dead shim files and unused agent implementations from `src/orchestrator/`. This reduces noise for subsequent phases and prevents dead code from being accidentally relocated into new module positions during absorption phases.

The target files are: `routers/` shim directory, `runners/agent_detector.py`, `runners/parsers/` shim directory, `runners/openhands.py`, `runners/openhands_docker.py`, `runners/openhands_common.py`, `runners/codex_server.py`, and `runners/codex_server_common.py`.

## Intent Verification
**Original Intent**: Phase 1 of the module consolidation plan — delete all dead shim files and deprecated re-export stubs with zero tolerance for backward-compat shims remaining.

**Functionality to Produce**:
- `src/orchestrator/routers/` directory entirely removed
- `src/orchestrator/runners/agent_detector.py` entirely removed
- `src/orchestrator/runners/parsers/` directory entirely removed
- `src/orchestrator/runners/openhands.py`, `openhands_docker.py`, `openhands_common.py` entirely removed
- `src/orchestrator/runners/codex_server.py`, `codex_server_common.py` entirely removed
- Zero import references to any deleted path in `src/`, `tests/`, `scripts/`, `alembic/`

**Final Verification Criteria**:
- All backend tests pass
- All frontend tests pass
- `grep` for each deleted module path returns zero results in `src/`, `tests/`, `scripts/`, `alembic/`
- `git status` shows only deletions, no new files in old locations

---

## Task 1: Audit and Delete `routers/` Shim Directory

**Description**:
`src/orchestrator/routers/` is a dead backward-compat shim directory containing two files: `__init__.py` (empty re-export) and `tasks.py` (re-exports `router` from `api.routers.tasks`). Confirm no consumers then delete entirely.

**Implementation Plan (Do These Steps)**

- [ ] Audit for consumers — search all of `src/`, `tests/`, `scripts/`, `alembic/` for any import of `orchestrator.routers`:
```bash
grep -r "from orchestrator.routers\|import orchestrator.routers" src/ tests/ scripts/ alembic/ --include="*.py"
```
- [ ] If any consumers are found, update them to import directly from `orchestrator.api.routers.*` instead of the shim. (Expected: zero consumers — these are already shims with no callers.)
- [ ] Delete the shim directory:
```bash
rm -rf src/orchestrator/routers/
```
- [ ] Confirm deletion:
```bash
ls src/orchestrator/routers/ 2>&1 || echo "Deleted OK"
```

**Constraints**:
- Only files under `src/orchestrator/routers/` are deleted. Do not touch `src/orchestrator/api/routers/`.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/routers/` no longer exists
- [ ] `src/orchestrator/api/routers/` is untouched and fully functional

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator.routers" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero results (excluding matches inside `api/routers/`)
- [ ] `ls src/orchestrator/routers/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.api.routers.tasks import router; print('ok')"` succeeds

---

## Task 2: Audit and Delete `runners/agent_detector.py`

**Description**:
`src/orchestrator/runners/agent_detector.py` is a registry-based detector that was intended to replace `detector.py` during a transition period. It is unused — `detector.py` is the active implementation. Confirm no consumers then delete.

**Implementation Plan (Do These Steps)**

- [ ] Audit for consumers:
```bash
grep -r "from orchestrator.runners.agent_detector\|import orchestrator.runners.agent_detector\|agent_detector" src/ tests/ scripts/ alembic/ --include="*.py"
```
- [ ] If any consumers are found, update them to use `orchestrator.runners.detector` (the active implementation) instead. (Expected: zero consumers.)
- [ ] Delete the file:
```bash
rm src/orchestrator/runners/agent_detector.py
```
- [ ] Confirm deletion:
```bash
ls src/orchestrator/runners/agent_detector.py 2>&1 || echo "Deleted OK"
```

**Constraints**:
- Only `runners/agent_detector.py` is deleted. `runners/detector.py` is the active implementation and must not be touched.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/agent_detector.py` no longer exists
- [ ] `src/orchestrator/runners/detector.py` is untouched

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "agent_detector" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero results
- [ ] `ls src/orchestrator/runners/agent_detector.py` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.runners.detector import detect_available_agents; print('ok')"` succeeds

---

## Task 3: Audit and Delete `runners/parsers/` Shim Directory

**Description**:
`src/orchestrator/runners/parsers/` contains backward-compat shims that re-export from `runners/agents/*/parser`. The real implementations live under `runners/agents/`. Confirm no consumers then delete the entire `parsers/` directory.

**Implementation Plan (Do These Steps)**

- [ ] Audit for consumers:
```bash
grep -r "from orchestrator.runners.parsers\|import orchestrator.runners.parsers" src/ tests/ scripts/ alembic/ --include="*.py"
```
- [ ] If any consumers are found, update them to import directly from the real locations:
  - `orchestrator.runners.parsers.claude_parser` → `orchestrator.runners.agents.claude_cli.parser`
  - `orchestrator.runners.parsers.codex_parser` → `orchestrator.runners.agents.codex.parser`
  - `orchestrator.runners.parsers.openhands_parser` → `orchestrator.runners.agents.openhands.parser`
  - `orchestrator.runners.parsers.base` → `orchestrator.runners.agents` (or whichever module defines the base protocols)
- [ ] Delete the shim directory:
```bash
rm -rf src/orchestrator/runners/parsers/
```
- [ ] Confirm deletion:
```bash
ls src/orchestrator/runners/parsers/ 2>&1 || echo "Deleted OK"
```

**Constraints**:
- Only files under `src/orchestrator/runners/parsers/` are deleted. Parser implementations under `runners/agents/*/` are untouched.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/parsers/` no longer exists
- [ ] Parser implementations under `runners/agents/claude_cli/`, `runners/agents/codex/`, `runners/agents/openhands/` are untouched

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator.runners.parsers" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero results
- [ ] `ls src/orchestrator/runners/parsers/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.runners.agents.claude_cli.parser import ClaudeStreamParser; print('ok')"` succeeds

---

## Task 4: Audit and Delete OpenHands Shim Files

**Description**:
`runners/openhands.py`, `runners/openhands_docker.py`, and `runners/openhands_common.py` are backward-compat shims re-exporting from `runners/agents/openhands/`. The real implementations live there. Confirm no consumers then delete all three shims.

**Implementation Plan (Do These Steps)**

- [ ] Audit for consumers of each shim:
```bash
grep -r "from orchestrator.runners.openhands\b\|from orchestrator.runners.openhands_docker\|from orchestrator.runners.openhands_common" src/ tests/ scripts/ alembic/ --include="*.py"
```
- [ ] If any consumers are found, update them to import directly from `orchestrator.runners.agents.openhands.agent` (or sub-modules as appropriate).
- [ ] Delete the three shim files:
```bash
rm src/orchestrator/runners/openhands.py
rm src/orchestrator/runners/openhands_docker.py
rm src/orchestrator/runners/openhands_common.py
```
- [ ] Confirm deletions:
```bash
ls src/orchestrator/runners/openhands.py src/orchestrator/runners/openhands_docker.py src/orchestrator/runners/openhands_common.py 2>&1 || echo "Deleted OK"
```

**Constraints**:
- Only the three root-level shim files are deleted. Files under `runners/agents/openhands/` are the real implementations and must not be touched.

**Functionality (Expected Outcomes)**:
- [ ] `runners/openhands.py`, `runners/openhands_docker.py`, `runners/openhands_common.py` no longer exist
- [ ] `runners/agents/openhands/` directory is untouched

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator.runners.openhands_common\|from orchestrator.runners.openhands_docker\|from orchestrator\.runners\.openhands\b" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero results
- [ ] `ls src/orchestrator/runners/openhands.py src/orchestrator/runners/openhands_docker.py src/orchestrator/runners/openhands_common.py` all fail with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.runners.agents.openhands.agent import OpenHandsAgent; print('ok')"` succeeds

---

## Task 5: Audit and Delete Codex Shim Files

**Description**:
`runners/codex_server.py` and `runners/codex_server_common.py` are backward-compat shims re-exporting from `runners/agents/codex/`. The real implementations live there. Confirm no consumers then delete both shims.

**Implementation Plan (Do These Steps)**

- [ ] Audit for consumers of each shim:
```bash
grep -r "from orchestrator.runners.codex_server\b\|from orchestrator.runners.codex_server_common" src/ tests/ scripts/ alembic/ --include="*.py"
```
- [ ] If any consumers are found, update them to import directly from `orchestrator.runners.agents.codex.agent` (or sub-modules as appropriate).
- [ ] Delete the two shim files:
```bash
rm src/orchestrator/runners/codex_server.py
rm src/orchestrator/runners/codex_server_common.py
```
- [ ] Confirm deletions:
```bash
ls src/orchestrator/runners/codex_server.py src/orchestrator/runners/codex_server_common.py 2>&1 || echo "Deleted OK"
```

**Constraints**:
- Only the two root-level shim files are deleted. Files under `runners/agents/codex/` are the real implementations and must not be touched.

**Functionality (Expected Outcomes)**:
- [ ] `runners/codex_server.py` and `runners/codex_server_common.py` no longer exist
- [ ] `runners/agents/codex/` directory is untouched

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator.runners.codex_server\b\|from orchestrator.runners.codex_server_common" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero results
- [ ] `ls src/orchestrator/runners/codex_server.py src/orchestrator/runners/codex_server_common.py` both fail with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.runners.agents.codex.agent import CodexServerAgent; print('ok')"` succeeds

---

## Task 6: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite and perform exhaustive grep verification that zero references to deleted paths remain anywhere in the repository. This is the gate check before Phase 1 is considered complete.

**Implementation Plan (Do These Steps)**

- [ ] Run backend unit tests:
```bash
uv run pytest tests/unit/ -v
```
- [ ] Run backend integration tests:
```bash
uv run pytest tests/integration/ -v
```
- [ ] Run frontend tests:
```bash
cd ui && npx vitest run
```
- [ ] If any test failures occur due to remaining imports of deleted modules, fix those imports and re-run the relevant test suite.
- [ ] Run the complete reference audit:
```bash
grep -r "from orchestrator\.routers" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "api/routers" || echo "OK: no routers shim refs"
grep -r "agent_detector" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: no agent_detector refs"
grep -r "from orchestrator\.runners\.parsers" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: no parsers shim refs"
grep -r "from orchestrator\.runners\.openhands_common\|from orchestrator\.runners\.openhands_docker\|from orchestrator\.runners\.openhands\b" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: no openhands shim refs"
grep -r "from orchestrator\.runners\.codex_server\b\|from orchestrator\.runners\.codex_server_common" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: no codex shim refs"
```
- [ ] Check for residual shim/stub markers:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/ --include="*.py" || echo "OK: no shim markers"
```
- [ ] Confirm git status shows only deletions:
```bash
git --no-pager status
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Every grep audit command above returns zero matches (or "OK:" echo)
- [ ] `git status` shows only deleted files — no new untracked files in old locations

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -rn "from orchestrator\.routers\|from orchestrator\.runners\.parsers\|from orchestrator\.runners\.openhands_common\|from orchestrator\.runners\.openhands_docker\|from orchestrator\.runners\.codex_server" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "api/routers"` returns zero lines
- [ ] `grep -rn "agent_detector" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `git --no-pager diff --stat HEAD` shows only file deletions for Phase 1 targets
