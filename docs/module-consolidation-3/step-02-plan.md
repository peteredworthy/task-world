# Step 2: Public Interface Audit

Turn the Step 2 planning slice into a bounded execution step that makes the top-level module contract actionable before any domain refactor starts. This step stays at the interface-planning layer: it documents canonical imports, export gaps, private symbol leaks, and migration batches that later implementation steps must follow.

The work here must remain small and reviewable. Each task produces one audit artifact or decision set that a later refactor step can consume directly without reopening Step 1 discovery.

## Step Artifacts

- Required Step 1 input: `docs/module-consolidation-3/step-01-audit.md`
- Required Step 2 output: `docs/module-consolidation-3/step-02-interface-audit.md`
- Required input references: Step 1 `F-XX` finding IDs
- Canonical path family for this tranche: `docs/module-consolidation-3/steps/step-0N-plan.md`

Every task in this file must remain atomic: fewer than 5 files changed and under roughly 500 lines of net edits. If the audit exposes a larger migration surface, stop and split the work.

## Intent Verification
**Original Intent**: Make the documented nine-module public contract executable by defining canonical top-level imports, missing exports, leaked internal-only symbols, and bounded migration batches before internal package movement begins.

**Functionality to Produce**:
- `docs/module-consolidation-3/step-02-interface-audit.md` mapping each in-scope module to its canonical top-level import paths
- A documented list of missing `__init__.py` exports that must be added before consumer migration
- A documented list of internal-only symbols that must stop leaking across module boundaries
- Ordered cleanup batches that group consumers by module and caller category
- Explicit forbidden-import review rules aligned with the repository's actual boundary enforcement
- Dependency notes that point each interface decision at the Step 3 or Step 4 batch expected to consume it

**Final Verification Criteria**:
- The completed audit covers runtime code, tests, scripts, migrations, startup callers, and transport-facing callers where applicable
- Every retained external symbol is assigned exactly one canonical top-level import path
- The audit names blockers for export conflicts, stale Step 1 evidence, or ownership ambiguity instead of deferring them silently
- Verification uses a policy-aligned check plus scoped caller searches, not only a broad grep

---

## Task 1: Record Module Export Audit Inputs

**Description**:
Create the audit scaffold for the nine top-level modules and tie it back to the verified Step 1 gap list so the rest of the step stays bounded by evidence.

**Implementation Plan (Do These Steps)**
- [ ] Create `docs/module-consolidation-3/step-02-interface-audit.md`.
- [ ] Add one row for each of the nine public modules with these required fields:
  - `module`
  - `scope_status` using one of `in_scope_now`, `no_issue_found`, or `out_of_scope_with_evidence`
  - `step_01_finding_ids`
  - `caller_categories`
  - `stop_condition`
- [ ] Require every `in_scope_now` or `out_of_scope_with_evidence` decision to cite at least one Step 1 `F-XX` finding.
- [ ] Record the caller categories for every in-scope module using an explicit checklist with `not_applicable` justification when needed:
  - runtime code
  - tests
  - scripts
  - migrations
  - startup callers
  - transport-facing/API-facing callers
- [ ] If Step 1 evidence is missing, stale, or does not identify exact findings, stop Step 2 and refresh Step 1 before defining canonical paths.

**Dependencies**
- [ ] `docs/module-consolidation-3/step-01-audit.md` exists and includes verified findings plus consumer inventories.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not add new boundary issues that are not backed by Step 1 evidence.
- [ ] Keep this task to audit inputs and gating criteria only.

**Functionality (Expected Outcomes)**
- [ ] The audit names which modules are in scope for Step 2 and why.
- [ ] Each in-scope module cites concrete Step 1 findings.
- [ ] Caller-category scope is explicit and reviewable.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-02-interface-audit.md` contains a nine-module scope table
- [ ] Every in-scope module references Step 1 `F-XX` findings
- [ ] Every caller category is either present or marked `not_applicable` with justification

---

## Task 2: Define Canonical Public Import Paths

**Description**:
Assign one canonical top-level import path to every symbol that remains externally consumable.

**Implementation Plan (Do These Steps)**
- [ ] Add a per-symbol decision table to `step-02-interface-audit.md` with these required columns:
  - `symbol`
  - `owner_module`
  - `current_import_paths`
  - `canonical_import_path`
  - `current_consumers`
  - `ownership_status` using one of `canonical_public_api`, `temporary_facade_to_remove`, or `internal_only`
  - `downstream_batch`
  - `blocker_state`
- [ ] Base the audit on live source plus Step 1 findings. Use `docs/ARCHITECTURE.md` as intent context only, not as sole ownership evidence.
- [ ] Record an explicit note when exposing a symbol from the module top level would require lazy loading, would change import-time behavior, or would risk a cycle.
- [ ] Treat conflicting canonical-path demands from different consumer categories as blockers with a named blocked future step.
- [ ] Require each retained symbol row to cite at least one current import site or Step 1 finding.

**Dependencies**
- [ ] Task 1 complete so the audit is limited to verified module scope.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)

**Constraints**
- [ ] Every retained external symbol must end with exactly one canonical top-level import path.
- [ ] Do not teach consumers new sub-package import paths as part of this step.

**Functionality (Expected Outcomes)**
- [ ] The audit tells implementers how to assign canonical top-level imports per symbol.
- [ ] Ownership ambiguity and compatibility-facade ambiguity are surfaced explicitly.
- [ ] Step 3 can consume the symbol table directly.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every retained symbol row has exactly one canonical import path
- [ ] Every blocker row names the blocked downstream step
- [ ] Symbols that would need lazy loading or introduce cycles are called out explicitly

---

## Task 3: Separate Missing Exports from Private Leaks

**Description**:
Distinguish symbols that need new public exports from symbols that must stop crossing module boundaries.

**Implementation Plan (Do These Steps)**
- [ ] Add two separate sections with separate tables:
  - `Missing Public Exports`
  - `Private Internal Leaks`
- [ ] Require every row in both tables to include:
  - `symbol`
  - `evidence_source`
  - `current_import_site`
  - `consumer_categories`
  - `planned_cleanup_type`
  - `downstream_dependency`
- [ ] Allow ambiguous cases only with an explicit dual-status note naming the primary classification and the secondary risk.
- [ ] Evaluate existing top-level exports as well as missing exports; current `__init__.py` exports may themselves be leaks.

**Dependencies**
- [ ] Task 2 complete so public symbols already have canonical paths.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not collapse missing-export work and private-leak cleanup into one mixed list.
- [ ] Keep caller categories explicit so later consumer sweeps remain bounded.
- [ ] Do not change source imports in this task.

**Functionality (Expected Outcomes)**
- [ ] The audit produces two separate outputs: missing exports and private leaks.
- [ ] Each private leak is linked to concrete consumer categories.
- [ ] Each entry states the expected cleanup mechanism or downstream dependency.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `Missing Public Exports` and `Private Internal Leaks` are both present
- [ ] Every row includes evidence, import site, consumer categories, cleanup type, and downstream dependency
- [ ] Ambiguous cases are recorded explicitly instead of silently collapsed

---

## Task 4: Build Ordered Cleanup Batches

**Description**:
Translate the interface decisions into bounded migration batches so later refactor steps can update one module and caller set at a time.

**Implementation Plan (Do These Steps)**
- [ ] Add a batch table to `step-02-interface-audit.md` with these required columns:
  - `batch_id`
  - `owner_module`
  - `symbols_covered`
  - `consumer_category`
  - `exact_consumer_files`
  - `old_paths_to_remove`
  - `target_future_step`
  - `active_runtime_call_site`
  - `batch_status` using one of `proposed`, `ready`, or `blocked`
- [ ] Split batches whenever they exceed one owner module, one consumer category, or the 5-file / 500-line target.
- [ ] Require any newly discovered high-risk caller outside the Step 1 inventory to trigger an inventory refresh before the batch may leave `proposed`.
- [ ] Require old import paths to be removed in the same batch that updates their consumers.

**Dependencies**
- [ ] Tasks 2 and 3 complete so public/export decisions and private-leak decisions are available.

**References**
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)

**Constraints**
- [ ] No deferred compatibility shims or duplicate import trees are allowed.
- [ ] Runtime-path replacements must name the active runtime call site being updated.

**Functionality (Expected Outcomes)**
- [ ] The audit defines bounded cleanup batches that later steps can execute directly.
- [ ] Inventory refresh becomes mandatory if new high-risk callers appear.
- [ ] Runtime and non-runtime callers are not blurred together accidentally.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every batch row includes exact consumer files and exact old paths to remove
- [ ] Oversized scope has been split into smaller batches
- [ ] Every runtime-affecting batch names an active runtime call site

---

## Task 5: Define Behavioral Verification for Later Refactors

**Description**:
Add concrete verification commands and review checks that later cleanup steps must reuse when enforcing the top-level module contract.

**Implementation Plan (Do These Steps)**
- [ ] Record the broad discovery scan only as a candidate review set:
```bash
rg "from orchestrator\\.(api|cli|config|db|envfiles|git|runners|state|workflow)\\.[^.]+\\.|import orchestrator\\.(api|cli|config|db|envfiles|git|runners|state|workflow)\\.[^.]+\\." \
  src tests scripts src/orchestrator/db/migrations \
  -g '*.py'
```
- [ ] Record the policy-aligned boundary check that later steps must reuse:
```bash
uv run python scripts/check_module_imports.py
```
- [ ] Add `uv run pyright` as the required regression check after any export-surface change.
- [ ] Require manual verification prompts covering runtime code, tests, scripts, migrations, startup callers, and transport-facing callers.
- [ ] Require any caller category not updated in the same phase to be recorded as a blocker.
- [ ] Require final audit notes to confirm that every retained symbol has exactly one canonical path and every leaked private symbol has a named cleanup batch or blocker.

**Dependencies**
- [ ] Tasks 1 through 4 complete so verification aligns with actual audit outputs.

**References**
- [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
- [docs/plan-runner/idea_to_plan_process.md](/Users/peter/code/task-world/worktrees/r51/docs/plan-runner/idea_to_plan_process.md)

**Constraints**
- [ ] Verification must test audit usability, not just document presence.
- [ ] Do not treat the broad grep output as automatic proof that every match is forbidden.

**Functionality (Expected Outcomes)**
- [ ] Later steps inherit a policy-aligned verification contract.
- [ ] Candidate import matches are distinguished from confirmed policy violations.
- [ ] Caller-category coverage remains part of verification, not an optional note.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-02-interface-audit.md` includes both the candidate review scan and the policy-aligned check
- [ ] `uv run pyright` is listed as a required regression gate
- [ ] Manual verification criteria cover runtime code, tests, scripts, migrations, startup callers, and transport-facing callers
