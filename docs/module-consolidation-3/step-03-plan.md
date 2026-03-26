# Step 3: Internal Consolidation by Domain

Execute internal consolidation through bounded domain batches that consume the verified findings from Step 1 and the canonical import decisions from Step 2. Every batch must update exports and direct consumers together, remove the obsolete path in the same pass, and leave the repository runnable before the next batch starts.

This step is implementation-facing rather than audit-only. It must still remain small and reviewable: each batch stays under 5 files changed and under roughly 500 lines of net edits. If a selected symbol or caller set cannot fit inside those limits, stop and split the work into another Step 3 batch before proceeding.

## Step Artifacts

- Required Step 1 input: `docs/module-consolidation-3/step-01-audit.md`
- Required Step 2 input: `docs/module-consolidation-3/step-02-interface-audit.md`
- Required Step 3 execution ledger: `docs/module-consolidation-3/step-03-batch-ledger.md`
- Required per-batch note path: `docs/module-consolidation-3/batches/step-03-<batch-id>.md`
- Canonical downstream sweep reference: `docs/module-consolidation-3/steps/step-04-plan.md`

Every Step 3 batch note must include:
- `batch_id`
- `domain`
- `step_01_finding_ids`
- `symbols_moved`
- `obsolete_import_prefixes`
- `canonical_import_prefixes`
- `exact_consumer_files`
- `active_runtime_call_site`
- `verification_commands`
- `deferred_cleanup_items` using `none` or an explicit blocker

## Intent Verification
**Original Intent**: Finish internal consolidation by domain in the order `workflow`/`state`, `runners`, `db`/`git`, then `api`/`config`, while enforcing the top-level module contract and removing obsolete internal paths in the same milestone that introduces the canonical path.

**Functionality to Produce**:
- One or more bounded refactor batches for each domain pair, each tied to exact Step 1 findings and Step 2 canonical import decisions
- Batch notes that identify the symbol moved, the old path removed, the exact consumer files updated, and the active runtime call site that proves the move matters
- Domain refactors that move public exports and direct consumers together, without compatibility shims, duplicate package trees, or deferred caller cleanup
- A reusable ledger that shows which domain batches completed, which verification commands ran, and whether any blocker stopped the step

**Final Verification Criteria**:
- Each completed batch records targeted behavioral verification proving the moved symbol is exercised through the canonical top-level import path
- Final per-step verification includes `uv run pytest tests/unit -v`, `uv run pyright`, `uv run ruff check .`, and `uv run python scripts/check_module_imports.py`
- Scoped searches for the exact obsolete prefixes removed in this step show no remaining external callers for completed batches
- No temporary compatibility modules, duplicate package trees, or silent deferred import-cleanup items remain in touched domains

---

## Task 1: Create the Step 3 Batch Ledger and Execution Gate

**Description**:
Create the control artifacts and stop/go rules that every Step 3 refactor batch must follow. This prevents later batches from drifting away from the Step 1 finding inventory or the Step 2 canonical import map.

**Implementation Plan (Do These Steps)**
- [ ] Create or refresh `docs/module-consolidation-3/step-03-batch-ledger.md`.
- [ ] Add one row per planned batch with these required fields:
  - `batch_id`
  - `domain`
  - `symbol`
  - `step_01_finding_ids`
  - `canonical_import_path`
  - `obsolete_import_prefixes`
  - `exact_consumer_files`
  - `active_runtime_call_site`
  - `status` using one of `planned`, `in_progress`, `completed`, or `blocked`
- [ ] Require every planned batch to cite at least one Step 1 `F-XX` finding and one Step 2 canonical import decision before code changes begin.
- [ ] Define the Step 3 stop conditions in the ledger or a short intro section:
  - batch scope exceeds 5 files or 500 lines
  - consumer inventory no longer matches live code
  - canonical owner is ambiguous
  - export change would create an unresolved import cycle
  - obsolete path cannot be removed in the same batch
- [ ] State that any stop condition forces a new batch split or a planning-doc refresh before implementation continues.

**Dependencies**
- [ ] `docs/module-consolidation-3/step-01-audit.md` identifies bounded findings and consumer inventories.
- [ ] `docs/module-consolidation-3/step-02-interface-audit.md` identifies canonical import paths and downstream batches.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md)

**Constraints**
- [ ] Keep this task to execution control artifacts and gates only.
- [ ] Do not start source refactors until the ledger can name exact findings, exact consumer files, and exact obsolete prefixes.

**Functionality (Expected Outcomes)**
- [ ] Step 3 has a single batch ledger that later batches can update directly.
- [ ] Every later batch starts from explicit findings, explicit consumers, and an explicit canonical path.
- [ ] Batch splitting and blocker handling are defined before any code movement starts.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `test -f docs/module-consolidation-3/step-03-batch-ledger.md`
- [ ] The ledger contains all required fields for planned batches
- [ ] Stop conditions are documented explicitly and require either batch-splitting or planning refresh

---

## Task 2: Execute the Next `workflow` / `state` Domain Batch

**Description**:
Start with the highest-risk ownership boundary. Each batch in this domain must cover one verified `workflow`/`state` leak at a time: event ownership, signaling helpers, callback interfaces, or runtime coordination seams already identified in Steps 1 and 2.

**Implementation Plan (Do These Steps)**
- [ ] Choose exactly one `workflow` or `state` symbol or responsibility from the Step 3 ledger that is marked ready by Step 1 and Step 2 evidence.
- [ ] Create `docs/module-consolidation-3/batches/step-03-<batch-id>.md` for the selected batch.
- [ ] Start the batch note with:
  - `batch_id`
  - `domain: workflow_state`
  - `symbol`
  - `old_import_path`
  - `new_canonical_import_path`
  - `step_01_finding_ids`
  - `exact_consumer_files`
  - `active_runtime_call_site`
- [ ] Add a pre-edit import sketch that shows:
  - current module-load direction
  - proposed module-load direction
  - whether adding a top-level export risks a circular import
- [ ] Update the top-level owner export only if Step 2 marked the symbol `canonical_public_api`.
- [ ] Update all direct consumers for the selected symbol in the same batch, including runtime code plus any listed tests, scripts, or startup wiring.
- [ ] Remove the obsolete cross-module internal import path in the same batch. Do not leave aliases, compatibility re-exports, or duplicate package trees behind.
- [ ] Record which symbol remains public and which helpers remain internal after the move.
- [ ] If the batch exceeds the file-count, line-count, or cycle-risk limit, stop and split it into another Step 3 batch before advancing.

**Dependencies**
- [ ] Task 1 complete: the batch ledger exists and identifies a ready `workflow`/`state` batch.
- [ ] Step 1 identifies the exact finding and full consumer list for the selected symbol.
- [ ] Step 2 defines the canonical public path or internal-only status for the selected symbol.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Keep each implementation batch under 5 files changed and under 500 lines of net edits.
- [ ] Do not change unrelated module boundaries in this task.
- [ ] Do not add a shim, deprecated import bridge, or duplicate module tree.

**Functionality (Expected Outcomes)**
- [ ] The selected `workflow`/`state` boundary leak is resolved through the documented top-level contract.
- [ ] All known consumers for the selected symbol use the canonical import path after the batch.
- [ ] The old cross-module import path is removed for the migrated symbol.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -v`
- [ ] Symbol-level smoke check proving the moved symbol loads from the top-level owner, for example:
```bash
uv run python -c "from orchestrator.workflow import <symbol>; print(<symbol> is not None)"
```
- [ ] A targeted behavior-oriented check proves the active runtime path changed, for example:
```bash
uv run pytest path/to/runtime_or_integration_test.py -v
```
Assertion requirement: exercise the workflow/state path that previously imported the internal symbol and assert the runtime path still completes the expected transition, callback, or state update through the canonical import surface.
- [ ] Scoped search for the exact obsolete prefixes recorded in the batch note returns no remaining external callers

---

## Task 3: Execute the Next `runners` Domain Batch

**Description**:
Refactor one bounded `runners` batch at a time so agent backends, detector/factory ownership, execution helpers, and profile-resolution consumers stop crossing into private `runners` internals.

**Implementation Plan (Do These Steps)**
- [ ] Select exactly one verified `runners` issue from the Step 3 ledger.
- [ ] Create the batch note at `docs/module-consolidation-3/batches/step-03-<batch-id>.md` and start it with the exact replaced call site in active code, such as executor startup, detector lookup, agent factory construction, or runner profile resolution.
- [ ] Record whether the touched top-level `orchestrator.runners` entry is:
  - a canonical public facade to retain
  - an obsolete compatibility bridge to remove
- [ ] Update `orchestrator.runners` exports only for symbols Step 2 marked as canonical public API.
- [ ] Move the selected symbol or responsibility behind the documented `runners` owner and update every direct consumer in the same batch.
- [ ] Remove the obsolete internal import path immediately after consumer migration.
- [ ] Stop and split the work if the batch touches more than 5 files, grows past 500 lines, or creates an import cycle.

**Dependencies**
- [ ] Task 1 complete: the batch ledger identifies a ready `runners` batch.
- [ ] Step 1 and Step 2 identify the exact finding, consumer list, and canonical path.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not defer a test, script, or startup consumer update for the selected symbol.
- [ ] Do not introduce a compatibility shim or leave both old and new paths active.

**Functionality (Expected Outcomes)**
- [ ] The selected `runners` boundary issue is resolved through a top-level `orchestrator.runners` import.
- [ ] All known consumers for the selected issue are migrated in the same batch.
- [ ] The obsolete internal path is removed for the migrated symbol.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -v`
- [ ] Symbol-level smoke check for the moved or exported object from `orchestrator.runners`
- [ ] A targeted runner-path verification exercises the actual touched path, for example a detector, factory, or execution helper test
Assertion requirement: perform the concrete runner action the batch changed and assert that the expected runner object, profile result, or execution path is produced through the canonical import surface.
- [ ] Scoped search for the exact obsolete `runners` prefixes recorded in the batch note returns no remaining external callers

---

## Task 4: Execute the Next `db` / `git` Domain Batch

**Description**:
Refactor one bounded `db`/`git` batch so persistence access remains behind `db` exports and repository or diff utilities remain behind `git` exports, with scripts, recovery logic, and migration callers updated in the same pass when applicable.

**Implementation Plan (Do These Steps)**
- [ ] Select exactly one verified `db` or `git` issue from the Step 3 ledger.
- [ ] Before editing, record a pre-batch search log for the exact old import path across:
  - runtime code
  - tests
  - scripts
  - `src/orchestrator/db/migrations/`
  - `src/orchestrator/db/recovery/`
- [ ] If the moved symbol is used in repository writes, reads, recovery, or migrations, record all those paths in the batch note and treat them as in-scope for this batch.
- [ ] Update `orchestrator.db` or `orchestrator.git` exports only when Step 2 marked the symbol public.
- [ ] Migrate all known direct consumers for the selected symbol in the same batch, including listed tests, scripts, recovery callers, and Alembic callers.
- [ ] Remove the obsolete internal import path immediately after consumer migration.
- [ ] Stop and split the batch if you hit the file-count, line-count, or circular-dependency limit.

**Dependencies**
- [ ] Task 1 complete: the batch ledger identifies a ready `db` or `git` batch.
- [ ] Step 1 identifies migration, script, recovery, and runtime consumers when relevant.
- [ ] Step 2 defines the canonical import path for the selected symbol.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Update migration or script callers in the same batch if the selected symbol is used there.
- [ ] Do not let either module become a shared utility backdoor.

**Functionality (Expected Outcomes)**
- [ ] The selected `db` or `git` boundary issue is resolved through the documented top-level module.
- [ ] All known consumers for the selected symbol are updated in the same batch.
- [ ] The old internal import path is removed for the migrated symbol.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -v`
- [ ] Symbol-level smoke check for the moved or exported object from `orchestrator.db` or `orchestrator.git`
- [ ] A targeted persistence or git-path verification proves behavior, for example:
```bash
uv run pytest path/to/integration_or_unit_test.py -v
```
Assertion requirement: if the batch touched persistence, assert the same repository read/write or recovery result still occurs through the canonical top-level import; if the batch touched git helpers, assert the expected repository or diff operation still succeeds through the top-level import.
- [ ] Scoped search for the exact obsolete prefixes recorded in the batch note returns no remaining external callers

---

## Task 5: Execute the Next `api` / `config` Domain Batch

**Description**:
Refactor one bounded `api`/`config` batch so transport-facing schemas remain under `api`, configuration models and profile resolution remain under `config`, and callers stop importing internal cross-module paths.

**Implementation Plan (Do These Steps)**
- [ ] Select exactly one verified `api` or `config` issue from the Step 3 ledger.
- [ ] Name the exact schema or config symbol, current owning file, old import path, new canonical path, and active route or config-loading call site before code changes begin.
- [ ] Update the owning module's top-level exports only when Step 2 marked the symbol public.
- [ ] Migrate all direct consumers for the selected symbol in the same batch, including route wiring, workflow callers, startup callers, and tests called out by the consumer inventory.
- [ ] Remove the obsolete internal import path immediately after all selected consumers are updated.
- [ ] Keep transport-only request or response models under `api` and config validation or profile mapping under `config`; do not solve the batch by reversing that dependency.
- [ ] Stop and split into another bounded batch if the change grows beyond limits or creates a reverse dependency from `config` into `api`.

**Dependencies**
- [ ] Task 1 complete: the batch ledger identifies a ready `api` or `config` batch.
- [ ] Step 2 defines the canonical public path for the selected symbol.
- [ ] Step 1 identifies route, startup, and test consumers for the selected symbol.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not import API request or response models into internal services when a local protocol or internal data object is sufficient.
- [ ] Do not leave obsolete transport or config cross-imports active after the batch.

**Functionality (Expected Outcomes)**
- [ ] The selected `api`/`config` boundary issue is resolved through the documented top-level contract.
- [ ] All known consumers for the selected symbol are migrated in the same batch.
- [ ] The obsolete internal import path is removed for the migrated symbol.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -v`
- [ ] Symbol-level smoke check for the moved or exported object from `orchestrator.api` or `orchestrator.config`
- [ ] A route-level or config-loading verification proves behavior
Assertion requirement: if the batch touched `api`, perform the route or app-loading action that uses the symbol and assert the expected response or model wiring still occurs; if it touched `config`, perform the config-loading or profile-resolution action and assert the expected validated model or resolved profile is returned.
- [ ] Scoped search for the exact obsolete prefixes recorded in the batch note returns no remaining external callers

---

## Task 6: Run the Obsolete-Path Sweep and Step Completion Gate

**Description**:
After all required domain batches are complete, run the final cleanup sweep for obsolete imports and prove the step ended without shims, duplicate trees, or deferred caller migrations.

**Implementation Plan (Do These Steps)**
- [ ] Update `docs/module-consolidation-3/step-03-batch-ledger.md` after every completed sub-batch with:
  - `batch_id`
  - `domain`
  - `symbol`
  - `files_changed`
  - `verification_run`
  - `status`
- [ ] Re-run policy-aligned import checks and scoped searches for all obsolete prefixes removed in this step.
- [ ] Re-check the Step 1 consumer inventories for every completed batch and confirm there are no deferred callers in tests, scripts, migrations, startup wiring, or policy tooling.
- [ ] Confirm every touched symbol now has one canonical top-level import path and that `deferred_cleanup_items` is `none` in every completed batch note.
- [ ] Confirm no compatibility shims, duplicate module trees, or temporary adapters were introduced anywhere in the completed batches.
- [ ] Run final per-step checks only after all required domain cleanup is complete.

**Dependencies**
- [ ] Tasks 2 through 5 complete for all bounded batches required by this step.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md)
- [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)

**Constraints**
- [ ] Do not mark this step complete if any consumer still relies on an obsolete internal path.
- [ ] Do not accept "temporarily exported from both places" as a green state.

**Functionality (Expected Outcomes)**
- [ ] All domain batches completed in this step satisfy the top-level module contract.
- [ ] No obsolete imports remain for the completed batches.
- [ ] No shims, duplicate trees, or deferred import-cleanup items remain in the touched domains.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -v`
- [ ] `uv run pyright`
- [ ] `uv run ruff check .`
- [ ] `uv run python scripts/check_module_imports.py`
- [ ] `docs/module-consolidation-3/step-03-batch-ledger.md` shows every executed batch and `deferred_cleanup_items: none` or an explicit blocker
