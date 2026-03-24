# Step 09 Dry-Run Analysis: Restructure runners/ Internals

**Date:** 2026-03-23
**Step:** Phase 9 — Move `runners/` flat files into `detection/` and `runtime/` sub-packages

---

## 1. Current State Snapshot

Confirmed by reading the actual worktree:

- `runners/__init__.py` currently contains **one line**: `"""Agent integrations for the orchestrator."""` — no re-exports
- `detection/` does **not** exist yet
- `runtime/` does **not** exist yet
- `execution/` already exists with `__init__.py`, `attempt_store.py`, `event_broadcaster.py`, `phase_handler.py` — good model for what the new sub-packages should look like
- Dead shim files still present at `runners/` root: `agent_detector.py`, `codex_server.py`, `codex_server_common.py`, `openhands.py`, `openhands_docker.py`, `openhands_common.py`, `action_log.py`, `agent_factory.py` — Phase 1 should have deleted these; their existence is noise but not a blocker
- **`scaffolding/` and `profiles/` sub-packages do NOT yet exist** in `runners/` — Phase 6 prerequisite not yet satisfied in this worktree (see failure mode F1)

---

## 2. Per-Task Analysis

### Task 1: Create runners/detection/ Sub-Package

**Assumptions:**
- `detector.py`, `profile_resolution.py`, `config_utils.py` each have no internal `orchestrator.runners.*` imports of their own that reference moved files — confirmed: `detector.py` imports from `runners.types`, `runners.agents.*`, and `config.enums` (none of which are moving)
- Files are copied first, deleted later (in Task 3) — correct, safe ordering

**Expected Outcomes:**
- Three files land in `detection/` with correct content
- Import verifications in the task's `Final Verification` section will pass

**Blockers / Concerns:**
- None for this task. The dependency direction is clean.

---

### Task 2: Create runners/runtime/ Sub-Package

**Assumptions:**
- None of the runtime files import from `orchestrator.runners.detector` etc. — confirmed: `monitor.py` imports from `config.enums`, `config.global_config`, `state.models`, `workflow.events`; `nudger.py` has no orchestrator imports at all; `quota.py` imports only `httpx`; `repetition_detector.py` imports only stdlib
- **Symbols listed in the verification command are all correct:**
  - `nudger.py`: `NudgeAction`, `Nudger`, `NudgerConfig`, `TimeProvider` ✓
  - `quota.py`: `FakeQuotaFetcher`, `QuotaFetcher`, `HttpQuotaFetcher` ✓
  - `repetition_detector.py`: `RepetitionDetector`, `RepetitionDetectorConfig`, `ReasoningDetectorConfig`, `ReasoningRepetitionDetector`, `RepetitionAction`, `ActionBudget`, `ActionBudgetConfig` ✓

**Expected Outcomes:**
- Four files land in `runtime/` with correct content

**Blockers / Concerns:**
- None. All files are self-contained pure-logic modules.

---

### Task 3: Update runners/__init__.py + Delete Original Flat Files

**Assumptions:**
- The current `__init__.py` docstring says `"""Agent integrations for the orchestrator."""`; the step's template uses `"""Agent runner integrations for the orchestrator."""` — minor wording change, no functional impact but executor should preserve or reconcile the existing docstring

**Expected Outcomes:**
- Re-exports added; seven flat files deleted
- `from orchestrator.runners import ToolDetector` etc. work via the re-export chain

**Blockers / Concerns:**

**F2 — Missing existing content preservation:** The step says "Preserve any existing content in `runners/__init__.py`". The current content is only a docstring, so nothing meaningful is lost. But if Phase 6 added content to `__init__.py` (for `scaffolding/` and `profiles/` re-exports), the step's template code block does NOT include those re-exports. **If the implementer simply pastes the template verbatim, it will clobber any Phase 6 re-exports.** The instruction "preserve existing content" requires reading the current file first.

**Hardening action:** Before writing `__init__.py`, grep for any existing non-docstring content. If Phase 6 re-exports are present (e.g., `from orchestrator.runners.scaffolding import ...` or `from orchestrator.runners.profiles import ...`), they must be merged into the new file, not overwritten.

**F3 — TimeProvider is a Protocol, not a concrete class:** It's still a valid export and can be imported/re-exported. No issue. But if a type checker is strict about re-exporting Protocol classes, it's worth noting that `TimeProvider` must appear in `__all__` to be explicit.

---

### Task 4: Update Internal runners/ Imports

**Line number accuracy — all confirmed against actual source:**
- `executor.py` line 43 (TYPE_CHECKING monitor), line 183 (lazy monitor), line 730 (lazy profile_resolution) ✓
- All agent file imports identified in the explorer match the step's instructions

**Assumptions:**
- `interface.py` line 5: the grep confirms `from orchestrator.runners.quota import QuotaFetcher` exists; line number is plausible but not confirmed exactly — functionally irrelevant since it's a simple line replacement

**Expected Outcomes:**
- 7 files updated with new sub-package import paths
- No behavioral changes

**Blockers / Concerns:**

**F4 — executor.py has TWO monitor imports at different places:** The step correctly identifies both (line 43 TYPE_CHECKING and line 183 lazy runtime import). Both must be updated. If an implementer only finds one via search and replace, the other will be missed. The grep pattern in the task catches both. No hardening needed beyond the existing grep verification step.

**F5 — No audit of `parsers/` sub-package:** `runners/parsers/` exists (base.py and stream parsers). The TYPE_CHECKING block in `claude_cli/agent.py` imports `from orchestrator.runners.parsers.base import StreamParser`. This module is NOT being moved, so no import change is needed here. The step correctly does not mention it. Confirmed safe.

**F6 — `agent_factory.py` not in the update list:** Confirmed by reading the file: `agent_factory.py` imports only from `orchestrator.config.enums`, `orchestrator.runners.errors`, and `orchestrator.runners.interface` — none of which are being moved. Correctly omitted from the update list.

---

### Task 5: Update External src/ Callers

**Confirmed line numbers:**
- `api/app.py` line 38 (TYPE_CHECKING monitor), line 478 (lazy ToolDetector) ✓
- `api/routers/runners.py` imports ToolDetector from `orchestrator.runners.detector` — confirmed
- `api/routers/runs.py` line 329 for AGENT_CONFIG_FIELDS — plausible (large file), not confirmed exactly
- `cli/agents.py` line 8 ToolDetector — plausible

**The NudgerConfig / global_config.py situation:**

`config/global_config.py` currently imports `NudgerConfig` from `orchestrator.runners.nudger` at lines 12 and 55 (confirmed). This is the C1 coupling that Phase 0 should have resolved.

**F7 — NudgerConfig fallback import path is wrong for C1 resolution:** The step says if Phase 0 hasn't fixed this, update `global_config.py` to `from orchestrator.runners import NudgerConfig as AgentNudgerConfig`. However, the intent of C1 is to move `NudgerConfig` to `config/models.py` so that Foundation no longer imports from Execution. Switching from `runners.nudger` to `runners` still leaves the Foundation→Execution coupling intact. The correct fix is `from orchestrator.config.models import NudgerConfig as AgentNudgerConfig`.

**Hardening action:** The step's fallback for global_config.py should be changed from `from orchestrator.runners import NudgerConfig` to `from orchestrator.config.models import NudgerConfig`. This is the correct C1 fix. If Phase 0 is already done, the grep returns nothing and this path is skipped. If Phase 0 is not done, the workaround should at minimum not leave a Foundation→Execution import.

**F8 — If Phase 0 is complete, global_config.py already imports from config.models, not runners.nudger.** The grep in Task 5 will return nothing, and this fallback is safely skipped. The step handles this correctly with the conditional "if present" check.

---

### Task 6: Update Test Imports

**Assumptions:**
- 12 test files are identified
- All 12 are confirmed by the import grep scan from the explorer

**F9 — Potential missed test files:** The explorer found all the referenced test files. No additional test files were found importing from the moved modules. The 12-file list appears complete.

**One discrepancy:** The test for `test_cli_agent.py` appears in both `tests/unit/` and `tests/integration/`. The step correctly lists both. Confirmed.

**Expected Outcomes:**
- All 12 files switch to `from orchestrator.runners import X`
- Tests still pass (purely import path change)

---

### Task 7: Full Test Suite and Final Reference Audit

**F10 — Pre-commit may fail on other issues:** The step runs `uv run pre-commit run --all-files` as the final check. This runs ruff, mypy, and other hooks. If any of the 7 deleted files had entries in ruff's ignore list or mypy's module stubs config, pre-commit could fail for unrelated reasons. Low risk but worth noting.

**F11 — `scripts/` directory not scanned for stale imports:** The step's final grep scans `src/ tests/ scripts/ alembic/`. Let's confirm the scripts/ directory doesn't import from moved modules. The step includes this in its final audit — good.

---

## 3. Global Failure Modes

### F1 (HIGH): Phase 6 Prerequisite Not Met

**Issue:** The step's intro says "After Phase 6, all absorptions into `runners/` are complete." But `runners/scaffolding/` and `runners/profiles/` do NOT exist in the current worktree. This means Phase 6 is not done.

If Step 9 is executed before Phase 6:
- `runners/__init__.py` won't yet have Phase 6 re-exports (so nothing is clobbered)
- But the step's verification will find the directory in an incomplete state
- More critically: the "Preserve existing content" instruction in Task 3 becomes irrelevant since there's nothing to preserve — but it also means the step could execute cleanly without Phase 6 being done

**Actual risk:** Step 9 has NO hard dependency on Phase 6 content — the detection/ and runtime/ sub-packages are completely independent of what Phase 6 adds. The prerequisite is advisory (to ensure all runners/ content is in place before the final `__all__` is written). The step will likely succeed even if Phase 6 isn't done, but the `runners/__init__.py` re-exports will be incomplete.

**Hardening action:** Add an explicit check at the start of Task 1:
```bash
ls src/orchestrator/runners/scaffolding/ 2>&1 || echo "WARNING: Phase 6 not complete — scaffolding/ missing"
ls src/orchestrator/runners/profiles/ 2>&1 || echo "WARNING: Phase 6 not complete — profiles/ missing"
```
Block execution if these are missing (or document the risk and proceed with awareness that Task 3's `__init__.py` will need updating in Phase 6).

### F2 (MEDIUM): runners/__init__.py Template May Clobber Phase 6 Re-exports

Covered in Task 3 analysis above. If Phase 6 is done first, the template must merge, not overwrite.

**Hardening action:** The step must explicitly read the current `__init__.py` content before writing and include all existing re-exports in the new version.

### F3 (LOW): global_config.py Fallback Uses Wrong Import Path for C1

Covered in Task 5 analysis above. The fallback import `from orchestrator.runners import NudgerConfig` preserves the Foundation→Execution coupling that C1 was designed to break. The correct path is `from orchestrator.config.models import NudgerConfig`.

**Hardening action:** Update the fallback instruction in Task 5 to use `from orchestrator.config.models import NudgerConfig as AgentNudgerConfig`. If Phase 0 is already done, this fallback is never reached.

### F4 (LOW): Docstring Wording Change in runners/__init__.py

Current: `"""Agent integrations for the orchestrator."""`
Step template: `"""Agent runner integrations for the orchestrator."""`

Functionally irrelevant but may trigger a ruff/pylint docstring check if one is configured. Preserving the existing docstring is safer.

**Hardening action:** Keep the existing docstring unchanged; append only the new import blocks below it.

### F5 (LOW): execution/ __init__.py is a Reference Model Not Cited

The existing `execution/__init__.py` has exactly the right structure for what detection/ and runtime/ should have: module-level re-exports + `__all__`. The step's `detection/` and `runtime/` `__init__.py` files are left empty (`touch`). The re-exports for these sub-packages go only into `runners/__init__.py`, not into `detection/__init__.py` or `runtime/__init__.py` directly.

**This is a design choice, not a bug.** External callers use `from orchestrator.runners import X` (top-level only), and internal callers use sub-package paths directly. The sub-package `__init__.py` files can remain empty or can mirror the `execution/__init__.py` pattern for discoverability. The step leaves them empty.

**Concern:** If a future reader wants to know what's in `detection/`, an empty `__init__.py` gives no clues. The `execution/` sub-package demonstrates the self-documenting pattern of re-exporting in the sub-package `__init__.py` too. This is not a blocker, but noting it as an architectural inconsistency.

---

## 4. Symbol Inventory Accuracy

All symbols listed in the `runners/__init__.py` template were verified against the actual source files:

| Module | Symbols | Verified |
|--------|---------|---------|
| `detector.py` | `ToolDetector`, `AGENT_CONFIG_FIELDS` | ✓ |
| `profile_resolution.py` | `resolve_model_for_profile` | ✓ |
| `config_utils.py` | `coerce_llm_config` | ✓ |
| `monitor.py` | `AgentRunnerMonitor` | ✓ |
| `nudger.py` | `NudgeAction`, `Nudger`, `NudgerConfig`, `TimeProvider` | ✓ |
| `quota.py` | `FakeQuotaFetcher`, `HttpQuotaFetcher`, `QuotaFetcher` | ✓ |
| `repetition_detector.py` | `RepetitionAction`, `RepetitionDetector`, `RepetitionDetectorConfig`, `ReasoningDetectorConfig`, `ReasoningRepetitionDetector`, `ActionBudget`, `ActionBudgetConfig` | ✓ |

No missing symbols. No phantom symbols. The `__all__` list in the step matches the actual exports.

---

## 5. Wiring Analysis

This step is purely structural — no new behavior is introduced. There is no "active code path" wiring concern. The re-exports in `runners/__init__.py` ensure that all callers (internal and external) can reach the same symbols via the same (or shorter) import paths. The moved files are functionally identical copies.

**No risk of a "build all components but wire nothing" failure mode.** All callers are explicitly enumerated and updated in Tasks 4, 5, and 6. Task 7's grep audit provides negative-space proof.

---

## 6. Summary of Hardening Actions

| ID | Priority | Action |
|----|----------|--------|
| H1 | HIGH | Add explicit Phase 6 prerequisite check at top of Task 1 (verify `scaffolding/` and `profiles/` exist before proceeding) |
| H2 | MEDIUM | Task 3: Read current `runners/__init__.py` first; merge Phase 6 re-exports if present rather than overwriting |
| H3 | LOW | Task 5: Change global_config.py fallback from `from orchestrator.runners import NudgerConfig` to `from orchestrator.config.models import NudgerConfig` (correct C1 resolution) |
| H4 | LOW | Task 3: Keep existing docstring wording (`"""Agent integrations for the orchestrator."""`) to avoid noise in pre-commit |
| H5 | LOW | Consider adding re-exports to `detection/__init__.py` and `runtime/__init__.py` to match `execution/__init__.py` pattern for discoverability (optional, not a blocker) |

---

## 7. Execution Confidence

**Overall risk: LOW.** This is a mechanical file-move-and-import-update phase with well-verified symbol inventories, confirmed line numbers, and a comprehensive grep audit at the end. The main risks are procedural (Phase 6 prerequisite, clobbering `__init__.py`), not structural. The step is well-specified.

No test logic is changed. No behavior is changed. All moved files are pure-logic or pure-config modules with no external I/O dependencies.
