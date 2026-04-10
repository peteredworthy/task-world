# Step 5: Final Boundary Proof

Prove the consolidation tranche is complete across the repository, not just within one refactor batch. This step is the final gate: rerun the import-discipline audit, execute the agreed verification matrix, confirm that no temporary structure remains, and record completion evidence against the tranche intent.

This step must not hide unfinished earlier work. If any final proof fails, stop and reopen the relevant earlier step instead of documenting a partial success. The repository is only release-ready when the documented nine-module public contract is true in code, in operational callers, and in final verification evidence.

## Step Artifacts

- Required Step 5 proof note: `docs/module-consolidation-3/step-05-final-proof.md`
- Required temporary-structure ledger input:
  - `docs/module-consolidation-3/step-03-batch-ledger.md`
  - `docs/module-consolidation-3/step-04-blockers.md`
- Required final-proof checklist section name inside the proof note: `Final Proof Checklist`
- Required intent-coverage table columns:
  - `intent_id`
  - `owning_step`
  - `evidence`
  - `status`

## Intent Verification
**Original Intent**: Prove the consolidation is complete with a repository-wide boundary audit, full verification matrix, and completion notes that map executed work back to the tranche intent.

**Functionality to Produce**:
- A final import-discipline audit covering touched source areas and operational callers
- Verification matrix results for tests, lint, type checks, and any shared-contract or startup checks affected by the tranche
- Explicit confirmation that no compatibility shims, duplicate module trees, or deferred cleanup items remain
- Completion notes mapping final outcomes back to prior step coverage and tranche intent

**Final Verification Criteria**:
- `uv run pytest` passes
- `uv run pyright` passes
- `uv run ruff check .` passes
- Repository-wide forbidden-import searches for the tranche-targeted internal module paths show no disallowed cross-module sub-package imports in operational callers or touched entry points
- Final notes show which prior step satisfied each covered intent item and identify any intentionally out-of-scope items without contradicting the tranche scope

---

## Task 1: Rebuild the Final Proof Scope From Prior Steps

**Description**:
Reconstruct the exact final-proof scope from the completed step artifacts before running repo-wide checks. This keeps the final audit tied to what actually landed instead of drifting into undocumented assumptions.

**Implementation Plan (Do These Steps)**
- [ ] Create `docs/module-consolidation-3/step-05-final-proof.md`.
- [ ] Add a `Final Proof Checklist` section with these required fields per row:
  - `area`
  - `caller_category`
  - `expected_rule`
  - `command`
  - `source_artifact`
- [ ] Review the completed outputs from Steps 2, 3, and 4 plus the tranche plan, and extract:
  - canonical import prefixes declared public
  - forbidden internal import prefixes targeted by this tranche
  - touched domains and exact caller categories or file paths that require final proof
- [ ] Do not treat any audit or verification command as evidence until it is present in the checklist.
- [ ] Stop if prior step artifacts do not clearly identify the canonical import map, touched caller set, or temporary-structure state.

**Dependencies**
- [ ] Steps 2 through 4 are complete enough to identify canonical import paths, touched domains, caller categories, and blocker state.

**References**
- [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md)
- [step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-03-plan.md)
- [step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md)
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)

**Constraints**
- [ ] Do not invent new module-contract rules in this task.
- [ ] Use one reference namespace consistently: the nested `steps/` path family plus the named execution artifacts.

**Functionality (Expected Outcomes)**
- [ ] Final proof scope is tied to completed earlier-step artifacts.
- [ ] The checklist names exact commands, caller categories, and boundary rules that must pass.
- [ ] Missing evidence from earlier steps is surfaced as a blocker before final verification begins.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-05-final-proof.md` contains a `Final Proof Checklist` with the required schema
- [ ] The checklist identifies exact `uv run` verification commands
- [ ] Any missing earlier-step evidence is either resolved or recorded as a stop condition

---

## Task 2: Run the Repository-Wide Import-Discipline Audit

**Description**:
Execute the final forbidden-import audit across touched operational callers and the entry points affected by this tranche. This audit must target actual internal paths prohibited by the tranche, not a generic search.

**Implementation Plan (Do These Steps)**
- [ ] Run category-specific searches for the exact forbidden prefixes from the final-proof checklist across:
  - `tests/**/*.py`
  - `scripts/**/*.py`
  - `src/orchestrator/db/migrations/env.py`
  - `src/orchestrator/db/migrations/versions/*.py`
  - `src/orchestrator/api/app.py`
  - `src/orchestrator/cli/main.py`
- [ ] Search both import forms for every forbidden prefix:
```bash
rg "from orchestrator\\.<forbidden_prefix>" tests scripts src/orchestrator/db/migrations src/orchestrator/api/app.py src/orchestrator/cli/main.py -g '*.py'
rg "import orchestrator\\.<forbidden_prefix>" tests scripts src/orchestrator/db/migrations src/orchestrator/api/app.py src/orchestrator/cli/main.py -g '*.py'
```
- [ ] Run the policy-aligned repository check:
```bash
uv run python scripts/check_module_imports.py
```
- [ ] Log every match in `step-05-final-proof.md` with:
  - `file`
  - `match`
  - `classification` using one of `allowed_same_module`, `false_positive`, or `blocker`
  - `reason`
- [ ] Stop and reopen the relevant earlier step if any `blocker` remains.

**Dependencies**
- [ ] Task 1 final-proof checklist is complete.

**Constraints**
- [ ] Do not use a broad `src` search as the only proof; it hides the real operational-caller question.
- [ ] Do not continue to Task 3 while a real forbidden import remains unresolved.

**Functionality (Expected Outcomes)**
- [ ] The repository has a classified final import audit covering operational callers and touched entry points.
- [ ] Any lingering forbidden import is identified by exact file path and treated as a blocker.
- [ ] Final proof only proceeds if the import-discipline audit is clean.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] The repository-wide forbidden-import search has been run against the caller categories in scope
- [ ] Every match is classified with file, match, classification, and reason
- [ ] There are zero unresolved forbidden imports before Task 3 starts

---

## Task 3: Execute the Final Verification Matrix

**Description**:
Run the agreed automated verification suite with `uv run` commands and capture results as tranche-completion evidence. These checks must run after the boundary audit is clean.

**Implementation Plan (Do These Steps)**
- [ ] Execute the repository-wide automated checks defined for final proof:
```bash
uv run pytest
uv run pyright
uv run ruff check .
```
- [ ] Run any additional shared-contract or startup smoke checks required by touched domains from earlier steps.
- [ ] Record each command result in `step-05-final-proof.md` with:
  - `command`
  - `pass_fail`
  - `rerun_count`
  - `reason_for_rerun`
  - `result_summary`
- [ ] For `pytest`, record suite summary counts and any skip-heavy areas relevant to touched domains.
- [ ] Stop and reopen the relevant earlier step if any verification command fails.
- [ ] Where integration tests are required, record assertion logic, not just scenario names.
Example assertion rule: if the final proof includes an API startup check, assert app creation succeeds through the canonical import path; if it includes a CLI check, assert the command exits successfully and no obsolete internal import remains in the exercised entry path.

**Dependencies**
- [ ] Task 2 import-discipline audit is clean.

**References**
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)

**Constraints**
- [ ] Use `uv run` for every Python-based verification command.
- [ ] Do not replace repository-wide checks with narrower substitutes for final sign-off.
- [ ] Do not treat zero-test collection or skipped behavior coverage as final proof if an earlier step required a stronger command.

**Functionality (Expected Outcomes)**
- [ ] Final proof includes passing repository-wide test, type, and lint evidence.
- [ ] Any domain-specific shared-contract or startup check required by earlier steps is included in the matrix.
- [ ] Failed verification reopens earlier work instead of becoming a follow-up TODO.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest`
- [ ] `uv run pyright`
- [ ] `uv run ruff check .`
- [ ] Any required touched-domain startup or shared-contract checks have been executed and recorded with assertion logic

---

## Task 4: Confirm No Temporary Structure or Deferred Cleanup Remains

**Description**:
Prove the tranche ended without compatibility layers, duplicate module trees, or deferred cleanup hiding behind green checks.

**Implementation Plan (Do These Steps)**
- [ ] Use the Step 3 batch ledger and Step 4 blocker log as the tranche-owned temporary-structure ledger.
- [ ] Check and log in `step-05-final-proof.md`:
  - any top-level compatibility bridge added by this tranche
  - any symbol exported from two public paths
  - any deferred cleanup marker tied to this tranche
- [ ] Record either:
  - `temporary_structure_status: clean`
  - or `temporary_structure_status: reopen_required` with the exact earlier step that must be reopened
- [ ] Stop final completion immediately if any shim, duplicate tree, or deferred cleanup item remains.

**Dependencies**
- [ ] Task 3 verification matrix has passed.

**Constraints**
- [ ] Do not accept dual-export or compatibility-bridge states as complete.
- [ ] Do not convert a remaining shim or deferred cleanup item into documentation-only debt.

**Functionality (Expected Outcomes)**
- [ ] Final proof explicitly confirms structural completion, not just passing automation.
- [ ] Any remaining temporary structure is treated as a blocker that reopens earlier work.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-05-final-proof.md` contains explicit temporary-structure status
- [ ] Step 3 and Step 4 ledgers show no unresolved tranche-owned shims or deferred cleanup items
- [ ] There are zero compatibility-bridge or duplicate-path blockers before Task 5 starts

---

## Task 5: Record Completion Notes and Reopen Earlier Steps on Any Failure

**Description**:
Capture the final tranche outcome in a form that maps directly back to the intent and step coverage. If any proof failed, record the failure as a reopen condition instead of issuing a misleading completion note.

**Implementation Plan (Do These Steps)**
- [ ] Add an intent-coverage table to `step-05-final-proof.md` with columns:
  - `intent_id`
  - `owning_step`
  - `evidence`
  - `status`
- [ ] Copy the intentionally out-of-scope items directly from `intent.md` into a separate `Out of Scope` section. Do not infer new ones.
- [ ] Add a final status field with only one of:
  - `release_ready`
  - `reopen_required`
- [ ] If final proof failed, add a reopen record naming:
  - `blocking_proof`
  - `reopen_owner_step`
  - `reason_final_signoff_is_blocked`
- [ ] Do not claim intent coverage that is not backed by completed earlier steps and final-proof evidence.

**References**
- [intent.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/intent.md)
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not produce a `release_ready` conclusion while any blocker remains.
- [ ] Do not use the out-of-scope section to excuse unfinished tranche work.

**Functionality (Expected Outcomes)**
- [ ] Completion notes tie the tranche outcome back to the documented intent and step sequence.
- [ ] Final sign-off is either evidence-backed or explicitly blocked with a reopen instruction.
- [ ] There is no ambiguity about whether the tranche is complete.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] The intent-coverage table exists with the required columns
- [ ] The out-of-scope section matches `intent.md` instead of inventing new exclusions
- [ ] If any final proof failed, the notes explicitly reopen the relevant earlier step instead of marking success
