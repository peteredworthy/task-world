# Dry Run Notes: Step 3 Internal Consolidation by Domain

## Summary

This step is directionally sound, but it is still too abstract to execute safely without drift. The biggest execution risks in the live repository are:

- The input step file lives at `docs/module-consolidation-3/steps/step-03-plan.md`, but the repository also has divergent copies at `docs/module-consolidation-3/step-03-plan.md` and other root-level step-plan files. The `steps/` tree is currently untracked in git, so a builder could execute against a document that is not the repository's committed source of truth.
- The required `rg "from orchestrator\\.(...)\\.[^.]+\\." src tests` verification is too broad. It currently matches many same-module internal imports in `src/`, so it cannot serve as a clean proof of forbidden cross-module leakage.
- Step 3 assumes Step 1 produced a verified consumer inventory and Step 2 produced a canonical import map, but this step only points to plan documents, not to concrete audit artifacts or symbol lists. A builder can "pick one leak" without a stable input set.
- Per-batch verification is under-specified for wiring. Unit tests plus `import orchestrator.<module>` can pass while runtime paths still use the old import site or a stale helper.

## Repo-Specific Findings

### File and reference checks

- `docs/module-consolidation-3/steps/step-03-plan.md` exists.
- `docs/module-consolidation-3/step-03-plan.md` also exists, and it is not identical to the `steps/` copy.
- The same divergence exists for Step 1, Step 2, and Step 4 plan files.
- `docs/module-consolidation-3/step-04-plan.md` exists, so the reference is valid.
- The requested output path `docs/module-consolidation-3/dry-run/step-03-plan-notes.md` did not exist before this run because the `dry-run/` directory was missing.

### Current import-state evidence

The repository already contains concrete internal-path consumers that Step 3 would need to handle deliberately, for example:

- `tests/integration/test_routine_loading.py` imports `orchestrator.config.routines.loader`
- `tests/unit/test_mcp_tool_definitions.py` imports `orchestrator.api.mcp.tools`
- `tests/unit/test_prune_ops.py` imports `orchestrator.git.ops.prune_ops`
- `tests/integration/test_api_agent_configs.py` imports `orchestrator.runners.profiles.service`

The repository also contains many internal same-module imports that the current regex will falsely treat as failures, for example:

- `src/orchestrator/workflow/service.py` imports `orchestrator.workflow.engine.transitions`
- `src/orchestrator/db/__init__.py` imports `orchestrator.db.access.repositories`
- `src/orchestrator/runners/__init__.py` imports multiple `orchestrator.runners.*` internals

### Existing facade/shim ambiguity

Some public surfaces are already thin wrappers or compatibility facades:

- `src/orchestrator/config/loader.py` explicitly says it re-exports from `orchestrator.config.routines.loader` "for compatibility"
- `src/orchestrator/runners/openhands.py`, `codex_server.py`, and related files are top-level facades over deeper internal packages

Step 3 forbids shims, but it does not define the difference between:

- an allowed canonical top-level facade inside a public module, and
- a forbidden compatibility bridge kept only to preserve an old internal path

Without that distinction, builders can make inconsistent decisions.

## Task-by-Task Dry Run

## Task 1: `workflow` / `state`

### Assumptions

- Step 1 already identified a specific `workflow`/`state` leak and listed all direct consumers.
- Step 2 already named the canonical top-level import path for that exact symbol.
- The selected leak can be fixed in 5 files or fewer.
- Updating `__init__.py` first will not create an import cycle.
- A package import smoke test is enough to prove the moved symbol is wired through active runtime paths.

### Expected outputs

- One concrete `workflow`/`state` leak is migrated.
- Any needed new export is added to `orchestrator.workflow` or `orchestrator.state`.
- Direct consumers move to the canonical import.
- The old internal cross-module path is removed for that symbol.
- Notes record what stayed public and what remained internal.

### Blockers and mitigation

- Blocker: the input inventory does not name the exact symbol and all consumers.
  Mitigation: require the batch to start with a named symbol list, file list, and consumer list copied from the Step 1 artifact.
- Blocker: `workflow.__init__` already re-exports a very large surface, including underscore-prefixed helpers from `workflow.engine.transitions`.
  Mitigation: force an explicit public/private decision for the selected symbol before editing.
- Blocker: top-level export changes can trigger circular imports across `workflow`, `state`, and `db`.
  Mitigation: require a pre-edit import sketch showing module-load direction and whether lazy import is needed.

### Failure modes

- The task says "select exactly one verified leak," but no artifact path identifies what is verified.
- "Record in implementation notes or PR description" is outside code, but the step has no required location for those notes.
- `uv run python -c "import orchestrator.workflow, orchestrator.state; print('ok')"` proves package import only, not that the moved symbol is imported from the new canonical path by active code.
- The regex verification will report internal same-module imports in `src/` and create false failures.
- Existing tests may still pass through old runtime wiring if only test imports were changed.

### Hardening actions

- Require the batch header to name: symbol, owner module, old import path, new canonical import path, and complete consumer file list.
- Require notes to be written to a fixed artifact path for each batch, not "implementation notes or PR description".
- Replace the generic package import smoke with symbol-level smoke, for example importing the exact moved symbol from the top-level owner.
- Replace the regex with a cross-module-only check. The check must exclude imports where importer and imported module share the same top-level owner.
- Add at least one targeted integration or workflow-service test for the touched runtime path before advancing.

## Task 2: `runners`

### Assumptions

- One `runners` leak can be isolated without touching more than 5 files.
- `orchestrator.runners.__init__` is the correct canonical surface for the selected symbol.
- Detector/factory ownership can be changed without affecting runtime construction elsewhere.
- Updating direct consumers in one batch is sufficient to ensure active runner execution now uses the new path.

### Expected outputs

- One `runners` boundary issue is consolidated behind `orchestrator.runners`.
- Direct consumers are updated in the same batch.
- The obsolete internal dependency is removed for that symbol.
- The repository still runs.

### Blockers and mitigation

- Blocker: `runners` is already a dense public surface with lazy exports and many agent-specific internal packages.
  Mitigation: require the selected symbol to be named before editing and require a dependency sketch of all importers.
- Blocker: factory and detector responsibilities are split across `agent_detector.py`, `agent_factory.py`, `detection/`, `profiles/`, `execution/`, and agent packages.
  Mitigation: require the batch to name what call site is being replaced, not just what symbol is re-exported.

### Failure modes

- The task can succeed cosmetically by exporting a symbol from `orchestrator.runners` while leaving active runtime code importing and constructing through the old internal path.
- Unit tests may continue passing because tests import the new top-level path, while runtime code still uses deep imports in executor/factory paths.
- The no-shim rule is ambiguous here because `runners` already contains top-level facade files such as `openhands.py` and `codex_server.py`.
- The verification command only imports `orchestrator.runners`, which does not prove the selected detector/factory/helper symbol is usable.

### Hardening actions

- Require each `runners` batch to name the replaced call site in active code, such as executor startup, detector lookup, or agent factory construction.
- Require a targeted integration test or startup smoke that exercises the actual runner path touched by the batch.
- Add an explicit rule distinguishing canonical top-level facades inside `runners` from forbidden compatibility bridges.
- Add symbol-level smoke imports for the moved/exported object, not only package import.

## Task 3: `db` / `git`

### Assumptions

- The selected boundary issue does not require schema changes.
- If the symbol is used in migrations or scripts, Step 1 already found those consumers.
- Moving imports behind `orchestrator.db` or `orchestrator.git` is enough to preserve persistence and repository semantics.

### Expected outputs

- One `db` or `git` leak is migrated behind the documented top-level module.
- Runtime code and known tests/scripts/migrations are updated together.
- The old internal path is removed for the migrated symbol.

### Blockers and mitigation

- Blocker: persistence-related symbols often have hidden recovery and migration consumers.
  Mitigation: require explicit searches in `src/orchestrator/db/migrations`, `src/orchestrator/db/recovery`, CLI code, and integration tests before selecting a batch.
- Blocker: `db.__init__` uses lazy `__getattr__` exports for repositories/event store to avoid cycles.
  Mitigation: require a cycle check before changing export ownership.

### Failure modes

- The step asks whether migrations or scripts are updated "where needed," but it does not define how to prove they were inspected.
- `uv run pytest tests/unit -v` will not catch all persistence/recovery breakage.
- The regex again over-matches same-module imports in `src/orchestrator/db/*` and `src/orchestrator/git/*`.
- The persistence-layer checklist in the prompt is not covered by the step. If a moved symbol touches repository read/write or event recovery paths, the batch could break replay/startup without changing tests.

### Hardening actions

- Require a pre-batch search log over runtime code, tests, scripts, and migrations for the exact old path.
- Add targeted integration tests for the affected persistence or git operation path.
- Add a mandatory checklist item: if the moved symbol is used in repository writes, reads, recovery, or migrations, verify all those code paths in the same batch.
- Replace package-import smoke with symbol-import smoke plus one operational smoke path, such as a recovery or git utility invocation covered by tests.

## Task 4: `api` / `config`

### Assumptions

- One `api` or `config` leak can be moved without creating reverse dependencies.
- The boundary between transport schema ownership and internal configuration ownership is clear for the chosen symbol.
- Tests and route wiring consumers are fully known in advance.

### Expected outputs

- One `api`/`config` boundary issue is corrected.
- Callers move to the canonical top-level contract.
- The old internal path is removed for the migrated symbol.

### Blockers and mitigation

- Blocker: the repository already has direct imports into `orchestrator.config.routines.*` and `orchestrator.api.mcp.*`, including tests and route code.
  Mitigation: require the selected leak to list exact callers before editing.
- Blocker: transport and config symbols often cross via route handlers, not just import statements.
  Mitigation: require at least one route-level or API integration test for the touched surface.

### Failure modes

- The task does not name any concrete schema or config symbol, so there is no model/class name to verify against actual source before implementation.
- A builder can "fix" tests to use top-level imports while leaving route wiring or workflow callers on the old internal path.
- The final verification imports only `orchestrator.api` and `orchestrator.config`, not the moved symbol.
- Existing compatibility surfaces like `orchestrator.config.loader` blur whether a facade is canonical or a temporary bridge.

### Hardening actions

- Require the batch spec to name the exact schema/config symbol and current owning file before code changes begin.
- Require route-level or config-loading integration coverage for the touched symbol.
- Require symbol-level top-level import smoke for the migrated object.
- Define whether top-level files such as `orchestrator.config.loader` are approved canonical APIs or cleanup targets.

## Task 5: Obsolete-Path Sweep and Completion Gate

### Assumptions

- Tasks 1 through 4 cover all needed domain batches for this step.
- The inventories from Step 1 are still current after all prior batches.
- A final regex sweep plus unit, pyright, and ruff checks is enough to prove completion.

### Expected outputs

- No obsolete imports remain for completed domain batches.
- No shims, duplicate trees, or deferred cleanup remain in touched domains.
- Final automated checks pass.

### Blockers and mitigation

- Blocker: Tasks 1 through 4 each describe one "next batch," but Step 3 also says a domain may require repeated batches.
  Mitigation: require a batch ledger that records every executed sub-batch per domain and blocks Task 5 until each planned batch is complete.
- Blocker: Step 1 inventories may become stale after each batch.
  Mitigation: require inventories to be refreshed after each batch before the final sweep.

### Failure modes

- Task 5 depends on "Tasks 1 through 4 complete for all bounded batches required by this step," but the task structure does not define how multiple batches per domain are tracked.
- The final regex still cannot distinguish forbidden cross-module imports from same-module imports.
- The final gate lacks targeted integration checks even though the architecture doc and Step 4 plan call them out.
- A repository can pass unit, pyright, and ruff while startup, migrations, API route loading, or workflow execution still use stale paths.

### Hardening actions

- Add a required execution ledger listing every domain batch, the symbol moved, the files changed, and the verification run.
- Replace the regex with a cross-module-only search or a small validation script that compares importer path to imported module owner.
- Add final targeted integration suites for every touched domain, not just unit tests.
- Add startup smokes for CLI/API/workflow entry points affected by the completed batches.

## Cross-Cutting Gaps To Fix Before Execution

1. Define one authoritative step-file location. The live repository currently has divergent root-level and `steps/` copies, and the `steps/` tree is untracked.
2. Replace the regex verification with a cross-module-only check. The current command will fail on legitimate same-module imports inside `src/`.
3. Require exact symbol selection before each batch. The current step never names concrete symbols, files, or call sites.
4. Require symbol-level smoke imports and active-path integration checks. Package imports alone do not prove wiring.
5. Define how public top-level facades differ from forbidden compatibility bridges. Current code already contains facade files and at least one explicit compatibility re-export.
6. Add a persistent batch ledger. Tasks 1 through 4 allow repeated batches, but Task 5 has no mechanism to know whether all required batches finished.

## Recommended Minimal Hardening Before A Builder Starts

- Freeze one authoritative source file for Step 3 and ignore the other copies.
- Attach the exact Step 1 inventory artifact and Step 2 canonical import map as required inputs.
- For each domain batch, require:
  - exact symbol name
  - old path
  - new canonical path
  - full consumer list
  - replaced runtime call site
  - batch note path
  - targeted unit and integration checks
- Replace the current `rg` proof with a cross-module import audit that does not flag same-module internal imports.
