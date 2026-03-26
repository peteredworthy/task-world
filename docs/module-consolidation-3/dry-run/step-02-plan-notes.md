# Dry Run Notes: Step 2 Public Interface Audit

This note simulates execution of [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md) against the live repository. It is analysis only.

## Summary

The step is directionally correct, but it is not hardened enough yet to guarantee a later builder produces a usable audit artifact. The main execution risks in the live repo are:

- The step mixes two document path families:
  - [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md)
  - [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-plan.md)
- The required forbidden-import review command does not match the repository's actual boundary rule. It returns many allowed same-module and root-file imports.
- Step 2 depends on Step 1 outputs, but it does not name a concrete Step 1 audit artifact path or finding-ID scheme to consume.
- The step is only about audit/planning output, but several verification bullets still prove document presence or grep output quality rather than whether the produced audit is actionable.
- Later-step wiring is still underspecified. A later refactor can add a top-level export while active runtime code continues to use the old internal path.

## Live Repository Checks Used For This Dry Run

- The nine documented public packages exist under `src/orchestrator/`: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`.
- Public `__init__.py` files exist for all nine modules:
  - [api/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/__init__.py)
  - [cli/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/__init__.py)
  - [config/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/config/__init__.py)
  - [db/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/__init__.py)
  - [envfiles/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/envfiles/__init__.py)
  - [git/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/git/__init__.py)
  - [runners/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/runners/__init__.py)
  - [state/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/state/__init__.py)
  - [workflow/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/workflow/__init__.py)
- The live export surfaces are uneven:
  - `workflow` and `runners` export very large surfaces and use lazy loading or compatibility facades.
  - `db` exports ORM models plus repositories via lazy `__getattr__`.
  - `api` lazy-loads router-task symbols and MCP tool symbols.
- `docs/ARCHITECTURE.md` is not fully aligned with the live tree. It still describes historical or proposed locations that no longer match the current package layout, so it cannot be treated as a precise source for symbol ownership.
- The forbidden-import command required by the step finds many hits that are not policy violations in this repo, including same-module imports inside `src/orchestrator/<module>/...` and allowed root-file imports such as `from orchestrator.config.routines.loader import ...`.
- The repository already has an enforcement script for module-boundary rules:
  - [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
- The step's required review command only searches `src tests`, but the step also says scripts and migrations must be covered. That search scope is incomplete for its own stated contract.

## Cross-Cutting Gaps In The Step File

- No concrete Step 1 artifact path is named. "Verified gap list and consumer inventory" exists as a concept, not a stable input file.
- No stable finding IDs are required, so later steps cannot reference interface decisions unambiguously.
- The step does not name the Step 2 output artifact to be produced beyond "the step document" or "audit notes".
- The step references the top-level plan copy in several places even though the active input is the nested `steps/` file.
- The step does not define whether top-level compatibility facades such as [config/loader.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/config/loader.py) or [runners/openhands.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/runners/openhands.py) are canonical API, temporary bridge, or cleanup target.
- The step asks later work to reuse its verification, but it does not require that later work prove active call sites were updated, only import surfaces.

## Task 1: Record Module Export Audit Inputs

### Assumptions

- Step 1 already produced a trustworthy module-by-module gap list and consumer inventory.
- The implementer can tell which modules are "affected" before starting the audit.
- Caller categories are derivable from Step 1 without reopening discovery.
- "Transport-facing/API-facing callers where relevant" is specific enough to apply consistently.

### Expected Outputs

- An audit scaffold listing the nine public modules.
- For each in-scope module, a pointer to Step 1 evidence showing why it needs audit attention.
- Per-module caller categories covering runtime code, tests, scripts, migrations, and transport-facing callers where relevant.
- A stop/go gate tied to Step 1 evidence freshness.

### Blockers And Mitigation

- Blocker: no concrete Step 1 artifact path or finding IDs.
  Mitigation: require the task to cite a single Step 1 audit file and specific finding IDs per module.
- Blocker: "affected module" is undefined.
  Mitigation: require every one of the nine modules to be classified as `in-scope now`, `explicitly no issue found`, or `out-of-scope with Step 1 evidence`.
- Blocker: caller-category scope is incomplete if search roots are not named.
  Mitigation: define minimum search roots: `src/`, `tests/`, `scripts/`, and `src/orchestrator/db/migrations/`.

### Failure Modes

- File-reference ambiguity:
  - The task can be executed against [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-plan.md) instead of the active nested step flow.
- Stale-evidence reuse:
  - A builder can restate Step 1 narrative without proving each module links to a concrete finding.
- Missing caller categories:
  - "Where relevant" lets builders omit scripts, migrations, or transport callers silently.
- Oversized scope:
  - If all nine modules are treated as active without a no-issue classification, the audit can expand past the small-step cap.

### Concrete Hardening Actions

- Require a fixed Step 1 input artifact path and a finding-ID column.
- Require a module-status table with one row for each of the nine modules.
- Replace "where relevant" with a required category checklist plus `not applicable` justification.
- Require a stop condition that names exactly what gets refreshed:
  - Step 1 finding
  - consumer inventory
  - or both

## Task 2: Define Canonical Public Import Paths

### Assumptions

- Current `__init__.py` files are the right source of truth for public interfaces.
- Every retained public symbol can be represented cleanly as `from orchestrator.<module> import <symbol>`.
- Conflicts between consumer groups will be obvious during the audit.
- Later cleanup batches can consume the audit directly if the step records a per-symbol decision.

### Expected Outputs

- A per-symbol decision table or equivalent for each in-scope module.
- Exactly one canonical top-level import path for each retained external symbol.
- Explicit blockers for symbols that cannot safely move to the top-level interface.
- A downstream batch reference for each retained symbol.

### Blockers And Mitigation

- Blocker: some current public surfaces are lazy-loaded or compatibility-oriented, not clean ownership boundaries.
  Mitigation: require a separate ownership column:
  - canonical public API
  - temporary compatibility facade
  - internal-only leak
- Blocker: the step does not define symbol granularity.
  Mitigation: require the unit of audit to be a named symbol, not a file or package bucket.
- Blocker: `docs/ARCHITECTURE.md` is not precise enough to resolve disputed ownership alone.
  Mitigation: treat live source plus Step 1 findings as primary evidence; use architecture docs only as intent context.

### Failure Modes

- Canonical-path table too vague:
  - A builder can write "use top-level imports" without enumerating symbols.
- Contract drift hidden:
  - A symbol can be marked canonical even if exposing it from `__init__.py` changes import-time behavior or creates cycles.
- Conflict handling underspecified:
  - "treated as blockers" does not define how blockers are recorded or what later steps are paused.
- Output not consumable:
  - A later Step 3 batch can know the symbol name but not the exact current import sites to migrate.

### Concrete Hardening Actions

- Require columns:
  - symbol
  - current import path(s)
  - canonical import path
  - current consumers
  - ownership status
  - downstream batch
  - blocker state
- Require explicit note when a top-level export would need lazy loading or would risk a cycle.
- Require blockers to include the blocked future step and the missing decision needed to proceed.
- Require each symbol row to cite at least one current import site or Step 1 finding.

## Task 3: Separate Missing Exports from Private Leaks

### Assumptions

- The audit can classify each symbol cleanly as missing-public-export or private-leak.
- Current import sites are available from Step 1 or easy to recover.
- Later fix type can already be predicted as export addition, consumer rewrite, or domain refactor dependency.

### Expected Outputs

- One missing-exports list.
- One private-leaks list.
- Consumer categories for every private leak.
- Evidence and expected cleanup mechanism for every entry.

### Blockers And Mitigation

- Blocker: some symbols may be both exported badly and owned by the wrong module.
  Mitigation: allow a dual-status note with a primary classification plus explicit secondary risk.
- Blocker: some current top-level exports may themselves be leaks.
  Mitigation: require the audit to evaluate existing `__init__.py` exports, not only missing ones.

### Failure Modes

- Classification collapse:
  - Builders can produce one mixed list and lose the distinction the later steps depend on.
- Missing evidence:
  - Entries can cite only "Step 1 found this" without naming the exact import site.
- Cleanup mechanism too generic:
  - "later refactor" can hide whether the real need is export work, ownership change, or consumer rewiring.
- Consumer coverage incomplete:
  - Private leaks can be tagged only for runtime code while tests, scripts, or migrations continue using them.

### Concrete Hardening Actions

- Require separate headings and separate tables for missing exports and private leaks.
- Require each row to include:
  - evidence source
  - current import site
  - consumer categories
  - planned cleanup type
  - downstream dependency
- Require a rule for ambiguous cases:
  - if both public-export and ownership issues exist, record both explicitly rather than choosing one silently.

## Task 4: Build Ordered Cleanup Batches

### Assumptions

- Symbol-level interface decisions from Tasks 2 and 3 can be grouped into atomic future batches.
- Module plus caller-category grouping is enough to keep later work bounded.
- Any high-risk caller discovered later should force an inventory refresh.

### Expected Outputs

- Ordered cleanup batches grouped by module and caller category.
- Entry prerequisites and expected consumer sets for each batch.
- A future-step mapping for each batch.
- A rule that old paths are removed in the same batch as consumer updates.

### Blockers And Mitigation

- Blocker: the step does not define what a "batch" artifact looks like.
  Mitigation: require a fixed batch table or checklist format.
- Blocker: the small-step size limit is stated, but there is no batching heuristic.
  Mitigation: require split triggers such as:
  - more than 5 files
  - more than one consumer category
  - or more than one owner module
- Blocker: newly discovered callers can invalidate prior grouping.
  Mitigation: require the batch to stay `proposed` until a refresh check confirms the inventory is still complete.

### Failure Modes

- Batch scope too large:
  - A builder can group all `config` test and runtime consumers into one batch that cannot stay under the limit.
- Future-step mapping ambiguous:
  - "Step 3 or later" is too loose for execution sequencing.
- Old-path removal not verifiable:
  - The step requires removal in the same batch but does not require listing the exact path(s) removed.
- No wiring proof:
  - Batches can update imports in tests and helper code while active runtime call sites remain untouched.

### Concrete Hardening Actions

- Require columns:
  - batch ID
  - owner module
  - symbols covered
  - consumer category
  - exact consumer files
  - exact old paths to remove
  - target future step
  - active runtime call site touched
- Require any batch that claims to replace a runtime path to name the active call site being updated.
- Require a split when a batch includes both runtime and non-runtime callers unless Step 1 proved they are inseparable.

## Task 5: Define Behavioral Verification For Later Refactors

### Assumptions

- The required `rg` command is a useful candidate review set.
- `uv run pyright` is sufficient as the regression check for export-surface changes made later.
- Manual verification prompts will be followed rigorously enough to catch coverage gaps.

### Expected Outputs

- The exact `rg` command included in the step document.
- `uv run pyright` included as a later regression check.
- Manual verification prompts covering runtime code, tests, scripts, migrations, and transport-facing callers.
- A final audit rule that every retained symbol has one canonical path and every private leak has a named cleanup batch or blocker.

### Blockers And Mitigation

- Blocker: the required `rg` command is inherently noisy in this repo.
  Mitigation: keep it as a candidate set if required, but add a second required policy-aligned check using [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py) or an equivalent cross-module-only filter.
- Blocker: `uv run pyright` checks typing, not consumer completeness.
  Mitigation: require symbol-specific import smoke and at least one runtime-path verification for batches that change active code.
- Blocker: the step says scripts and migrations matter, but the grep command ignores them.
  Mitigation: require explicit manual searches for those roots per batch.

### Failure Modes

- False confidence from grep:
  - Same-module imports in `src/orchestrator/workflow/*`, `src/orchestrator/db/*`, and `src/orchestrator/runners/*` will appear as hits even when allowed.
- False confidence from pyright:
  - Type checks can pass while runtime code still imports old internal paths or lazy exports hide wiring drift.
- Caller categories still skipped:
  - The manual prompt says "where relevant", so a builder can omit migrations or scripts without recording why.
- Component wiring not enforced:
  - A future batch can add a new top-level export and migrate some imports while the active code path continues using the old internal module.

### Concrete Hardening Actions

- Require the exact `rg` command plus a second required review pass that filters to cross-module sub-package imports only.
- Require manual verification to include an explicit category matrix with `checked`, `not applicable`, or `blocker`.
- Require each later batch to name:
  - the old active call site
  - the new active import path
  - and the proof that the old path is no longer used
- Require at least one symbol-level smoke import for changed exports and one active-path test for runtime-affecting batches.

## Additional Repo-Specific Failure Modes

- [workflow/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/workflow/__init__.py) currently re-exports underscore-prefixed helpers from `workflow.engine.transitions`. Step 2 does not say whether these are legitimate public API or existing leaks to retire.
- [db/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/__init__.py) explicitly documents backward-compatible ORM-model re-exports. Step 2 does not define whether compatibility exports of this kind are acceptable end state.
- [api/__init__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/__init__.py) lazy-loads router and MCP symbols. Step 2 does not define whether lazy-loaded transport helpers belong in the canonical public surface.
- Tests currently include many direct internal imports that later Step 3 batches would need to rewrite, for example:
  - [test_routine_loading.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_routine_loading.py)
  - [test_mcp_server.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_mcp_server.py)
  - [test_prune_ops.py](/Users/peter/code/task-world/worktrees/r51/tests/unit/test_prune_ops.py)
  - [test_agent_service.py](/Users/peter/code/task-world/worktrees/r51/tests/unit/test_agent_service.py)

## Wiring Analysis

This step does not introduce runtime components, but it does create planning outputs that later refactors must actually use. The current failure mode is planning-wire drift:

- Step 2 can produce canonical import decisions without naming the active runtime call sites that later steps must replace.
- Step 3+ could then add top-level exports and update a few test imports while the executor, API startup, workflow runtime, or repository layer continues importing from internal paths.

Hardening actions:

- Require every Step 2 symbol decision that affects runtime code to name at least one active call site in the current codebase.
- Require every cleanup batch to identify what replaces what:
  - old import path
  - new canonical path
  - active caller file(s)
  - proof that old caller path was removed
- Require later runtime-affecting batches to verify the active path, not only importability of the new export.

## Items That Are Not Applicable For This Step

- New model/class name validation: this step defines audit instructions only and does not introduce new source types.
- Async and infrastructure dependency resolution: no new runtime behavior is introduced in this step.
- Persistence-layer completeness: no DB schema, repository read/write path, or migration changes should occur in this step.
- Existing tests breaking due to code changes: if Step 2 remains documentation-only, code tests should not change. The real risk is that its later verification guidance is too weak.

## Recommended Hardening Changes To The Step

1. Name one Step 1 input artifact path and require finding IDs.
2. Name one Step 2 output artifact path and required table formats.
3. Keep the exact required `rg` command, but pair it with a policy-aligned boundary check.
4. Require category matrices for runtime, tests, scripts, migrations, and transport-facing callers with explicit `not applicable` justifications.
5. Require every symbol and every future batch to name exact current import sites.
6. Add wiring requirements for runtime-affecting symbols so later steps must prove active call-site replacement, not just export availability.
