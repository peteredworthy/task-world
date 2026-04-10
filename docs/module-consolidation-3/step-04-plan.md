# Step 4: High-Risk Consumer Sweep

Validate the callers most likely to break after a completed Step 3 domain refactor batch. This step turns the Step 1 consumer inventory and Step 2 interface decisions into an explicit merge gate for tests, scripts, migrations, startup wiring, and other operational callers before the next domain batch begins.

This step is caller-focused rather than module-focused. Run it once per completed Step 3 domain batch. It is not complete until every inventoried non-source consumer is either migrated to the canonical top-level import path or recorded as an immediate blocker for the batch.

## Step Artifacts

- Required Step 3 input: `docs/module-consolidation-3/step-03-batch-ledger.md`
- Required batch note input: `docs/module-consolidation-3/batches/step-03-<batch-id>.md`
- Required Step 4 checklist output: `docs/module-consolidation-3/step-04-consumer-sweep-<batch-id>.md`
- Required blocker log: `docs/module-consolidation-3/step-04-blockers.md`
- Required recurring gate note: `docs/module-consolidation-3/step-04-recurring-gates.md`

## Intent Verification
**Original Intent**: Validate high-risk consumers after each domain refactor so non-source callers do not silently preserve obsolete internal module imports.

**Functionality to Produce**:
- A completed consumer validation checklist for the finished Step 3 domain batch
- Updated tests, scripts, migrations, and startup paths that still import obsolete internal module paths for that batch
- A blocker record for any caller that cannot be migrated within the same phase
- Reusable "must inspect before merge" checks for the next domain batch

**Final Verification Criteria**:
- Domain-relevant `uv run pytest` targets covering the touched caller set pass
- `uv run ruff check .` passes after any caller updates
- Targeted searches for the completed domain batch show no obsolete internal imports in tests, scripts, migrations, or startup paths
- Startup wiring and operational tooling import through top-level module interfaces
- Any unresolved caller is documented as a blocker, not deferred cleanup

---

## Task 1: Refresh the Consumer Sweep Scope for the Completed Domain Batch

**Description**:
Rebuild the exact consumer checklist for the domain batch that just finished Step 3. This keeps the sweep tied to current code instead of stale assumptions.

**Implementation Plan (Do These Steps)**
- [ ] Read the completed Step 3 batch note together with the Step 1 consumer inventory and the Step 2 canonical import decisions.
- [ ] Create `docs/module-consolidation-3/step-04-consumer-sweep-<batch-id>.md` with these required columns:
  - `file_path`
  - `caller_category`
  - `current_import`
  - `canonical_import`
  - `status` using one of `already_canonical`, `migrate_in_step_4`, `false_positive`, or `blocker`
  - `note`
- [ ] Restrict searches to non-source callers plus explicit startup entry points. At minimum inspect:
  - `tests/**/*.py`
  - `scripts/**/*.py`
  - `src/orchestrator/db/migrations/env.py`
  - `src/orchestrator/db/migrations/versions/*.py`
  - `src/orchestrator/api/app.py`
  - `src/orchestrator/cli/main.py`
  - `scripts/serve.py`
  - `scripts/worker.py`
- [ ] Search both import forms for the exact obsolete prefixes from the Step 3 batch note:
```bash
rg "from orchestrator\\.<obsolete_prefix>" tests scripts src/orchestrator/db/migrations src/orchestrator/api/app.py src/orchestrator/cli/main.py -g '*.py'
rg "import orchestrator\\.<obsolete_prefix>" tests scripts src/orchestrator/db/migrations src/orchestrator/api/app.py src/orchestrator/cli/main.py -g '*.py'
```
- [ ] Stop if the Step 1 inventory or Step 2 interface map is no longer accurate for the completed batch. Update the planning docs before proceeding.

**Dependencies**
- [ ] Step 3 is complete for at least one domain batch and produced a batch note with exact obsolete and canonical prefixes.
- [ ] Step 1 and Step 2 artifacts still exist for that batch.

**References**
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)
- [step-02-interface-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-interface-audit.md)
- [step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-03-plan.md)

**Constraints**
- [ ] Do not edit production code in this task unless the only change is correcting a stale checklist artifact.
- [ ] Do not start caller migration until every remaining match has been categorized.

**Functionality (Expected Outcomes)**
- [ ] The completed domain batch has a current consumer checklist covering all required non-source caller categories.
- [ ] Every candidate obsolete import is classified before migration work starts.
- [ ] Stale planning assumptions are surfaced immediately.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] A written checklist exists for the completed batch with the required schema
- [ ] Both import forms have been searched for the exact obsolete prefixes
- [ ] Any mismatch between the live code and earlier artifacts is resolved or recorded as a stop condition

---

## Task 2: Inspect Tests and Operational Callers Category by Category

**Description**:
Walk the high-risk callers in bounded groups so the sweep does not blur unrelated failures. The goal is to prove each category was checked.

**Implementation Plan (Do These Steps)**
- [ ] Inspect tests listed in the batch checklist and record exact file paths.
- [ ] Inspect scripts and operational tooling listed in the checklist, including at minimum:
  - `scripts/serve.py`
  - `scripts/worker.py`
  - `scripts/seed_db.py`
  - `scripts/restore_from_journal.py`
  - `scripts/check_module_imports.py` when policy tooling is affected
- [ ] Inspect migrations listed in the checklist under `src/orchestrator/db/migrations/`.
- [ ] Inspect startup wiring through explicit entry points:
  - `src/orchestrator/api/app.py`
  - `src/orchestrator/cli/main.py`
  - `scripts/serve.py`
  - `scripts/worker.py`
- [ ] Record one of three outcomes for each caller:
  - `already_on_canonical_path`
  - `requires_migration_in_task_3`
  - `blocker_requires_step_reopen`
- [ ] Record one validation command per inspected caller when feasible.
- [ ] For tests, do not record only a scenario name. Record the assertion logic the later executor must prove.
Example assertion rule: if a test validates caller migration, name the exact action and the expected outcome, such as "import the canonical symbol and assert the old internal import no longer appears in the module under test" or "exercise the route/startup path and assert it loads through the top-level interface."

**References**
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)
- [step-01-audit.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-audit.md)

**Constraints**
- [ ] Keep inspection batches atomic: one caller category per pass.
- [ ] Do not mark a category complete until each inventoried caller has an outcome and, where feasible, a validation command.

**Functionality (Expected Outcomes)**
- [ ] Tests, scripts, migrations, startup wiring, and operational tooling have explicit inspection results.
- [ ] The migration set for Task 3 is bounded to concrete files.
- [ ] Assertion logic is documented for every test-based verification in scope.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every caller category from Task 1 has an inspection result
- [ ] Every caller marked for migration is identified by exact file path
- [ ] Test-based validations include assertion logic, not just scenario labels

---

## Task 3: Migrate Remaining High-Risk Callers to Canonical Public Imports

**Description**:
Update the remaining callers found in Task 2 so they import through the canonical top-level module interfaces defined in Step 2. Perform this in small edit batches that keep the repository runnable.

**Implementation Plan (Do These Steps)**
- [ ] Update one bounded caller batch at a time. Each batch should stay under 5 files and under 500 lines changed.
- [ ] Replace obsolete imports with the canonical top-level path already approved in Step 2.
- [ ] Use caller-specific verification patterns instead of generic import-only smoke checks:
  - tests:
```bash
uv run pytest path/to/updated_test.py -v
```
Assertion requirement: execute the exact test path tied to the updated caller and assert the expected behavior still succeeds through the canonical import.
  - CLI startup:
```bash
uv run python -m orchestrator.cli.main --help
```
Assertion requirement: command exits successfully and help output renders without importing the obsolete internal path.
  - API startup:
```bash
uv run python -c "from orchestrator.api import create_app; app = create_app(db_path=':memory:', routine_dirs=[]); assert app is not None"
```
Assertion requirement: app creation succeeds through the top-level API surface.
  - server script:
```bash
uv run python -c "import scripts.serve; assert scripts.serve.app is not None"
```
Assertion requirement: the server entry module loads and exposes the expected app object through canonical imports.
  - worker script:
```bash
ORCHESTRATOR_DB=/tmp/step4.db uv run python -c "import scripts.worker; print('ok')"
```
Assertion requirement: the worker module loads without using the obsolete import path.
  - migrations:
```bash
uv run alembic -c alembic.ini upgrade head
```
Assertion requirement: migration environment imports and upgrade execution succeed without the obsolete internal path.
- [ ] Re-run targeted obsolete-import searches after each edit batch using the exact obsolete prefixes from the batch note.
- [ ] Continue until the completed domain batch has no remaining obsolete imports in its inventoried high-risk callers.

**Dependencies**
- [ ] Task 2 has produced an exact file list for the migration set.

**Constraints**
- [ ] Only update callers that belong to the completed domain batch.
- [ ] Do not introduce compatibility shims or duplicate import paths.
- [ ] If a caller needs new interface work beyond Step 2, stop and move it to Task 4 as a blocker.

**Functionality (Expected Outcomes)**
- [ ] Remaining high-risk callers for the completed batch use canonical top-level imports.
- [ ] Each edit batch is independently verifiable and keeps the codebase runnable.
- [ ] Obsolete imports are removed from the completed batch's non-source callers.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Relevant caller-specific verification commands pass
- [ ] Targeted searches show no obsolete imports remaining in the migrated caller set
- [ ] The active entry point for each updated startup or script caller has been exercised

---

## Task 4: Record and Escalate Any Unresolved Caller as a Blocker

**Description**:
Any caller that cannot be migrated in the same phase must stop the batch. This task makes blockers explicit and prevents deferred cleanup.

**Implementation Plan (Do These Steps)**
- [ ] Write unresolved callers to `docs/module-consolidation-3/step-04-blockers.md`.
- [ ] For each blocker, record:
  - `batch_id`
  - `file_path`
  - `current_obsolete_import`
  - `expected_canonical_import`
  - `reason_it_cannot_be_fixed_now`
  - `owner_step` using one of `step_01`, `step_02`, or `step_03`
  - `restart_condition`
- [ ] Record the batch status in `step-04-consumer-sweep-<batch-id>.md` as one of:
  - `complete`
  - `stopped_blocked`
- [ ] Stop the milestone if any blocker exists. Do not leave TODOs or "fix later" notes for callers that belong to the completed batch.

**Constraints**
- [ ] No deferred TODOs.
- [ ] No scattered blocker notes outside the named blocker log and batch checklist.

**Functionality (Expected Outcomes)**
- [ ] Every unresolved caller is documented as a blocker with enough detail to restart safely.
- [ ] The completed batch cannot be merged while a high-risk caller blocker remains.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every unresolved caller has a blocker record in `step-04-blockers.md`
- [ ] Every batch checklist has a `complete` or `stopped_blocked` status
- [ ] There are zero untracked unresolved callers for the completed batch

---

## Task 5: Capture Recurring Merge-Gate Checks for the Next Domain Batch

**Description**:
Convert the completed sweep into a reusable gate for the next Step 3 domain batch so the same caller categories are inspected deliberately every time.

**Implementation Plan (Do These Steps)**
- [ ] Record recurring checks in `docs/module-consolidation-3/step-04-recurring-gates.md`.
- [ ] For each recurring check, capture:
  - `command`
  - `caller_category`
  - `why_it_exists`
  - `failure_it_caught_in_this_batch`
- [ ] If the sweep discovered a missing recurring gate in the tranche docs, update the recurring list in the named recurring-gates file or the tranche plan in the same change.
- [ ] Keep the note short and operational so it can be reused without re-discovery.

**References**
- [step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-03-plan.md)
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)

**Constraints**
- [ ] Record only checks that proved behavior or import loading, not mere file presence.
- [ ] Do not broaden the next batch checklist beyond evidence gathered in this sweep.

**Functionality (Expected Outcomes)**
- [ ] The next domain batch has explicit recurring merge-gate checks for high-risk callers.
- [ ] The sweep's caller knowledge is retained in a reusable form with provenance.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-04-recurring-gates.md` exists
- [ ] Each recurring check records command, caller category, rationale, and failure caught
- [ ] The recorded checks are behavior-oriented and derived from the completed sweep
