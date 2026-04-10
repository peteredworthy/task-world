# Dry-Run Analysis: Step 1 — Delete Dead Code

## Executive Summary

Step 1 is mostly correct in its approach but contains a **critical false assumption**: the step plan labels the OpenHands and Codex shim files as "dead" with "Expected: zero consumers," when in fact they have **many active consumers** — including `src/orchestrator/api/app.py` (production code) and ~20 test files. Additionally, `runners/parsers/base.py` contains real protocol definitions that are not a shim and need special handling. The three truly-dead targets (routers/, agent_detector.py, parsers/ shims) are correctly identified. The step plan's fallback ("If any consumers are found, update them") covers the recovery path, but the agent must be prepared to do significant import update work rather than simple deletions.

---

## Task-by-Task Analysis

### Task 1: Delete `routers/` Shim Directory

**Assumptions:**
- `src/orchestrator/routers/` contains only `__init__.py` and `tasks.py`
- Zero consumers across `src/`, `tests/`, `scripts/`, `alembic/`
- `src/orchestrator/api/routers/` is distinct and untouched

**Verified against actual codebase:**
- ✅ Only two files: `__init__.py` (empty comment) and `tasks.py` (re-exports `router` from `api.routers.tasks`)
- ✅ Zero consumers — grep confirms no `from orchestrator.routers` imports anywhere
- ✅ `src/orchestrator/api/routers/` is the real implementation (12 files)

**Expected outputs:** Directory deletion succeeds without any import updates needed.

**Blockers:** None.

**Failure modes:** None identified. This task is straightforward.

---

### Task 2: Delete `runners/agent_detector.py`

**Assumptions:**
- `agent_detector.py` is unused with zero consumers
- `detector.py` is the active implementation and is separate

**Verified against actual codebase:**
- ✅ Zero consumers — grep confirms no `agent_detector` imports anywhere
- ✅ `detector.py` exists at `runners/detector.py` as the active implementation
- `agent_detector.py` defines a `AgentDetector` protocol, `_DETECTORS` registry, and public functions (`register_detector()`, `detect_all()`, `get_config_schema()`, `get_detector_registry()`) — none of these are called from any other file

**Expected outputs:** File deletion succeeds without any import updates needed.

**Blockers:** None.

**Failure modes:** None identified. This task is straightforward.

---

### Task 3: Delete `runners/parsers/` Shim Directory

**Assumptions:**
- `parsers/` contains only backward-compat shims re-exporting from `runners/agents/*/parser`
- Zero consumers of `from orchestrator.runners.parsers`
- Parser implementations under `runners/agents/*/` are untouched

**Verified against actual codebase:**
- ✅ `claude_parser.py`, `codex_parser.py`, `openhands_parser.py` are shims
- ✅ Zero consumers — grep confirms no `from orchestrator.runners.parsers` imports anywhere
- ⚠️ **CRITICAL GAP**: `parsers/__init__.py` uses `__getattr__()` for lazy loading — code accessing `runners.parsers.ClaudeStreamParser` (attribute access, not import statement) would not be caught by `grep -r "from orchestrator.runners.parsers"`. The grep pattern in Task 3 only catches `from` imports, not attribute-style access. However, since there are zero `from` imports, attribute-style access is also likely zero.
- ⚠️ **CRITICAL GAP**: `parsers/base.py` is NOT a shim — it contains real protocol definitions (base parser protocols). The step plan treats all of `parsers/` as shims, but `base.py` appears to contain live interface code. If any file accesses `parsers.base` via the `__getattr__` lazy loader, deleting `parsers/` would silently break it.

**Hardening action for parsers/base.py:**
1. Read `parsers/base.py` to confirm whether it contains real protocols or just re-exports
2. If it contains real protocols: grep for any consumers (`base`, `BaseParser`, etc.) across the whole codebase before deleting
3. If protocols exist there but are also defined elsewhere, verify the real definition location
4. If `parsers/base.py` defines protocols that are only accessed via the lazy loader, those protocols may need to be moved to `runners/interface.py` or a similar canonical location before deletion

**Expected outputs:** Assuming `base.py` is confirmed to be either a shim or unused, directory deletion succeeds without import updates.

**Blockers:** Must confirm `parsers/base.py` content before proceeding.

---

### Task 4: Delete OpenHands Shim Files

**Assumptions (as stated in step plan):**
> "If any consumers are found, update them to import directly from `orchestrator.runners.agents.openhands.agent`"
> "(Expected: zero consumers)"

**Verified against actual codebase — ASSUMPTION IS WRONG:**
- ❌ `openhands.py` has **9 consumers**:
  - `src/orchestrator/api/app.py` (production code)
  - `tests/unit/test_openhands_health.py`
  - `tests/unit/test_openhands_custom_tools.py`
  - `tests/unit/test_openhands_tool_filtering.py`
  - `tests/unit/agents/test_openhands_quota.py`
  - `tests/integration/test_openhands_agent.py`
  - `tests/integration/test_api_agents.py`
  - `tests/integration/test_quota_live.py`
- ❌ `openhands_docker.py` has **2 consumers**:
  - `tests/unit/test_openhands_docker.py`
  - `tests/integration/test_openhands_docker_agent.py`
- ❌ `openhands_common.py` has **4 consumers**:
  - `tests/unit/test_openhands_common.py`
  - `tests/unit/test_openhands_custom_tools.py`
  - `tests/unit/test_prompt_generation.py`
  - `tests/unit/test_openhands_docker.py`

**Impact:** The step plan's fallback ("If any consumers are found, update them") means this is recoverable, but the agent must update ~11 distinct files (1 production + ~10 test files) before deleting the shims.

**Specific import migration table:**

| Shim | Real Location | Re-exported symbols |
|------|--------------|---------------------|
| `runners.openhands` | `runners.agents.openhands.agent` | `OpenHandsAgent`, `_SDK_AVAILABLE`, `_build_openhands_mcp_config`, `_obs_get_req` |
| `runners.openhands_docker` | `runners.agents.openhands.docker_agent` | `DockerOpenHandsAgent`, `_SDK_AVAILABLE`, `_DOCKER_WORKSPACE_AVAILABLE`, `_detect_platform` |
| `runners.openhands_common` | `runners.agents.openhands.common` | `CallbackRegistry`, `DEFAULT_OPENHANDS_TOOLS`, `build_openhands_prompt`, `extract_metrics`, `register_builtin_tools`, and many more |

**Wiring concern:** `app.py` imports `OpenHandsAgent` from the shim. After the shim is deleted and `app.py` is updated, verify the import works from the real path (no circular imports introduced).

**Failure modes:**
1. **Private symbol access**: Shims re-export private symbols (`_SDK_AVAILABLE`, `_build_openhands_mcp_config`, etc.). Test files that import these private symbols via the shim must import them from the real module instead. This works as long as those symbols are still defined in the real module — verify before updating.
2. **Wildcard re-exports**: Shims use `from module import *`. Some test files may use the shim for wildcard access. Need to audit exactly which names each test actually uses.

---

### Task 5: Delete Codex Shim Files

**Assumptions (as stated in step plan):**
> "(Expected: zero consumers)"

**Verified against actual codebase — ASSUMPTION IS WRONG:**
- ❌ `codex_server.py` has **8 consumers**:
  - `src/orchestrator/api/app.py` (production code)
  - `tests/unit/test_executor_codex.py`
  - `tests/unit/test_codex_server_agent.py`
  - `tests/unit/test_codex_server_callbacks.py`
  - `tests/unit/test_codex_server_parity.py`
  - `tests/unit/test_codex_server_transport.py`
  - `tests/integration/test_codex_server_callbacks.py`
- ❌ `codex_server_common.py` has **6 consumers**:
  - `tests/unit/test_codex_server_common.py`
  - `tests/unit/test_codex_server_parity.py`
  - `tests/unit/test_codex_server_tool_filtering.py`
  - `tests/unit/test_prompt_generation.py`
  - `tests/integration/test_codex_server_callbacks.py`

**Impact:** ~10 distinct files (1 production + ~9 test files) need import updates before deletion.

**Specific import migration table:**

| Shim | Real Location | Key Re-exported symbols |
|------|--------------|------------------------|
| `runners.codex_server` | `runners.agents.codex.agent` | `CodexServerAgent`, `RealStdioTransport` |
| `runners.codex_server_common` | `runners.agents.codex.common` | `CODEX_SERVER_TOOL_ALLOWLIST`, `JsonRpcTransport`, `build_codex_server_prompt`, `build_dynamic_tool_call_response`, `enforce_tool_allowlist`, and many more |

**Failure modes:**
1. **Private symbol access**: Same risk as Task 4 — shims re-export private symbols. Verify they're still exported from the real module.
2. **Large wildcard surface**: `codex_server_common` re-exports ~16 symbols via `*`. Test files may use any of them.

---

### Task 6: Full Test Suite and Final Reference Audit

**Assumptions:**
- All backend unit and integration tests pass
- All frontend tests pass
- All reference greps return zero results

**Verified gaps:**
- ✅ The grep commands in the step plan are well-structured
- ⚠️ The `from orchestrator\.runners\.openhands\b` pattern uses a word boundary `\b`. This is a regex, but `grep -r` uses BRE by default — `\b` is not standard in BRE. The step plan's grep commands use `\b` which requires `-P` (Perl regex) or `-E` (extended) for reliable matching. Without `-P` or `-E`, `\b` may be silently treated as literal `\` + `b` and produce wrong results.

**Hardening action:** Add `-P` flag to grep commands that use `\b` word boundaries, or restructure the pattern to avoid `\b` (e.g., use `from orchestrator\.runners\.openhands[^_]` or `from orchestrator\.runners\.openhands import`).

- ⚠️ No `alembic/` directory exists in this worktree — alembic audit step will silently find nothing but that's correct.

---

## Summary of Failure Modes and Hardening Actions

### FM1: False "zero consumers" assumption for OpenHands/Codex shims [HIGH SEVERITY]

**Description:** The step plan describes Tasks 4 and 5 as deletions of dead files with zero consumers. In reality, both have many active consumers including production `app.py`.

**Impact:** If the agent follows the "Expected: zero consumers" guidance and skips the audit step, it will delete files that break the application and many tests.

**Hardening:** The step plan's fallback handles this correctly — but the executing agent must run the audit grep first and not skip it based on the "expected" annotation. The step instructions should be reordered: **audit first, update imports, then delete**. The "Expected: zero consumers" annotation should be removed or replaced with "May have consumers — audit is mandatory."

### FM2: `parsers/base.py` may contain real code [MEDIUM SEVERITY]

**Description:** The step plan treats all of `parsers/` as a shim directory, but `parsers/base.py` is identified as "base protocols (real code, not a shim)." If it defines protocols that are used elsewhere (possibly via the lazy `__getattr__` mechanism in `__init__.py`), deleting it silently breaks those consumers.

**Hardening:**
1. Read `parsers/base.py` before deleting
2. If it contains protocol definitions, grep for those protocol names across the codebase
3. If consumers exist, move the protocols to `runners/interface.py` or appropriate location before deleting `parsers/`

### FM3: Word boundary `\b` in grep commands may not work in BRE [LOW SEVERITY]

**Description:** Verification grep commands in Tasks 4, 5, and 6 use `\b` word boundary, which is not standard BRE.

**Hardening:** Add `-P` flag (Perl regex) to all grep commands using `\b`:
```bash
grep -rP "from orchestrator\.runners\.openhands\b" src/ tests/ ...
```
Or restructure to avoid `\b`:
```bash
grep -r "from orchestrator\.runners\.openhands " src/ tests/ ...
```

### FM4: Private symbol access through shims [MEDIUM SEVERITY]

**Description:** Shims re-export private symbols (`_SDK_AVAILABLE`, `_build_openhands_mcp_config`, `_DOCKER_WORKSPACE_AVAILABLE`, `_detect_platform`, `_obs_get_req`). After import path updates, tests importing these names must import from the real module. If the real module has since renamed or removed these private symbols, the import update itself will fail.

**Hardening:** Before updating any test import, verify that the private symbol still exists at the real path:
```bash
grep -n "_SDK_AVAILABLE\|_build_openhands_mcp_config\|_DOCKER_WORKSPACE_AVAILABLE" \
  src/orchestrator/runners/agents/openhands/agent.py \
  src/orchestrator/runners/agents/openhands/docker_agent.py
```

### FM5: `app.py` import update may introduce circular imports [LOW SEVERITY]

**Description:** `app.py` currently imports `OpenHandsAgent` and `CodexServerAgent` through shims. After updating to import directly from `runners.agents.openhands.agent` and `runners.agents.codex.agent`, a new import chain through the `api/` → `runners/agents/` path is established. If those agent modules import from `api/` (unlikely but possible given coupling C6), a circular import would result.

**Hardening:** After updating `app.py` imports, run `uv run python -c "from orchestrator.api.app import app; print('ok')"` before running the full test suite to catch circular import errors early.

### FM6: Test files import multiple shims in one file [LOW SEVERITY]

**Description:** Some files import from multiple shims (e.g., `test_openhands_custom_tools.py` imports from both `openhands` and `openhands_common`; `test_openhands_docker.py` imports from both `openhands_docker` and `openhands_common`). Import updates must handle all imports in each file atomically.

**Hardening:** When updating a test file, scan the full file for all shim imports and update them all in one pass rather than piecemeal.

---

## Revised Execution Order Recommendation

To minimize risk given the actual state of the codebase:

1. **Tasks 1–3** (routers, agent_detector, parsers) — straightforward deletions, no consumers, do these first
2. **Audit parsers/base.py** — read the file, check for real protocols, move if needed
3. **Update all consumers for Tasks 4–5** — update `app.py` first, then test files, grouped by shim
4. **Delete shim files** only after all consumers are updated and `uv run python -c "..."` spot checks pass
5. **Run full test suite** (Task 6) — expect some failures if wildcard re-exports from shims included symbols not yet tracked down
6. **Final grep audit** — using `-P` flag for `\b` patterns

---

## Files That Need Import Updates (Enumerated)

### For OpenHands shims (Tasks 4):
| File | Imports to update |
|------|------------------|
| `src/orchestrator/api/app.py` | `runners.openhands.OpenHandsAgent` → `runners.agents.openhands.agent.OpenHandsAgent` |
| `tests/unit/test_openhands_health.py` | `runners.openhands.*` |
| `tests/unit/test_openhands_custom_tools.py` | `runners.openhands.*`, `runners.openhands_common.*` |
| `tests/unit/test_openhands_tool_filtering.py` | `runners.openhands.*` |
| `tests/unit/agents/test_openhands_quota.py` | `runners.openhands.*` |
| `tests/integration/test_openhands_agent.py` | `runners.openhands.*` |
| `tests/integration/test_api_agents.py` | `runners.openhands.*` |
| `tests/integration/test_quota_live.py` | `runners.openhands.*` |
| `tests/unit/test_openhands_docker.py` | `runners.openhands_docker.*`, `runners.openhands_common.*` |
| `tests/integration/test_openhands_docker_agent.py` | `runners.openhands_docker.*` |
| `tests/unit/test_openhands_common.py` | `runners.openhands_common.*` |
| `tests/unit/test_prompt_generation.py` | `runners.openhands_common.*` |

### For Codex shims (Task 5):
| File | Imports to update |
|------|------------------|
| `src/orchestrator/api/app.py` | `runners.codex_server.CodexServerAgent` → `runners.agents.codex.agent.CodexServerAgent` |
| `tests/unit/test_executor_codex.py` | `runners.codex_server.*` |
| `tests/unit/test_codex_server_agent.py` | `runners.codex_server.*` |
| `tests/unit/test_codex_server_callbacks.py` | `runners.codex_server.*` |
| `tests/unit/test_codex_server_parity.py` | `runners.codex_server.*`, `runners.codex_server_common.*` |
| `tests/unit/test_codex_server_transport.py` | `runners.codex_server.*` |
| `tests/integration/test_codex_server_callbacks.py` | `runners.codex_server.*`, `runners.codex_server_common.*` |
| `tests/unit/test_codex_server_common.py` | `runners.codex_server_common.*` |
| `tests/unit/test_codex_server_tool_filtering.py` | `runners.codex_server_common.*` |
| `tests/unit/test_prompt_generation.py` | `runners.codex_server_common.*` |

**Total: ~22 files need import updates** (1 production + ~21 test files). This is the dominant work item in Step 1.
