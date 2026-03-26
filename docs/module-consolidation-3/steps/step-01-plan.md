# Step 1: Reality Audit and Gap List

Establish the live-code baseline for Module Consolidation 3 before any structural refactor begins. This step converts the tranche-level discovery milestone into a bounded execution file that produces evidence-backed audit notes, a verified gap list, stable finding IDs, and explicit downstream gates for later interface cleanup and domain refactors.

This step is documentation-first but still behavioral: each claim must be backed by live repository evidence, not by restating older planning text. If discovery shows the planning docs are stale or contradictory, execution stops at the documentation correction instead of carrying stale assumptions into later steps.

## Step Artifacts

- Required audit output: `docs/module-consolidation-3/step-01-audit.md`
- Required finding ID format: `F-01`, `F-02`, `F-03`, ...
- Canonical downstream step references for this tranche:
  - `docs/module-consolidation-3/steps/step-02-plan.md`
  - `docs/module-consolidation-3/steps/step-03-plan.md`
  - `docs/module-consolidation-3/steps/step-04-plan.md`
  - `docs/module-consolidation-3/steps/step-05-plan.md`

## Intent Verification
**Original Intent**: Satisfy M0 from `docs/module-consolidation-3/plan.md` by validating the nine-module architecture against the live repository and separating confirmed consolidation issues from stale assumptions before any code movement.

**Functionality to Produce**:
- `docs/module-consolidation-3/step-01-audit.md` with sections `Repository Baseline`, `Verified Gap List`, `Consumer Inventory`, and `Dependencies and Gates`
- A module-by-module inventory of affected consumer categories for each verified finding: runtime code, tests, scripts, migrations, startup wiring, and policy tooling where applicable
- Stable finding IDs that later steps can cite directly
- A documented stop/go rule for stale-doc mismatches, unresolved consumer scope, or import-rule contradictions

**Final Verification Criteria**:
- Every claimed boundary issue in `step-01-audit.md` is traceable to live repository evidence
- Every finding row has a stable `F-XX` identifier and a status of `verified`, `not_found`, `docs_stale_code_ok`, or `docs_code_conflict_stop`
- Later consolidation steps can cite specific Step 1 finding IDs instead of generic audit narrative
- `uv run pytest tests/unit -v` either passes or is recorded explicitly as `blocked_environment` with captured command output

---

## Task 1: Confirm the Nine-Module Baseline Against the Repository Layout

**Description**:
Audit the live package layout and current import graph for `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`. This task creates the factual baseline that all later gap claims must reference.

**Implementation Plan (Do These Steps)**
- [ ] Create `docs/module-consolidation-3/step-01-audit.md` and add a `Repository Baseline` section.
- [ ] Record the observed status of all nine documented public modules under `src/orchestrator/`.
- [ ] Add a required classification table for root-level `src/orchestrator/*.py` peers such as `executor.py`, `errors.py`, `time_utils.py`, and `__version__.py` using one of: `public surface`, `shim/facade`, or `internal utility`.
- [ ] Define `material contradiction` concretely in the audit output as one or more of:
  - missing documented package
  - extra package acting as a public entry point
  - root-level peer file acting as an undocumented public surface or shim
  - mismatch between the documented import rule and the enforced import rule
- [ ] Run and record two separate discovery passes:
```bash
rg "from orchestrator\\.[^.]+\\.|import orchestrator\\.[^.]+\\." src tests scripts src/orchestrator/db/migrations -g '*.py'
uv run python scripts/check_module_imports.py
```
- [ ] Summarize the first command as a noisy baseline sample only. Treat the second command as the policy-aligned import-discipline check.
- [ ] Stop and document the mismatch if the live package layout materially contradicts `docs/module-consolidation-3/plan.md` or `docs/ARCHITECTURE.md`.

**Dependencies**
- [ ] None. This is the entry task for the tranche.

**References**
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)
- [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)

**Constraints**
- [ ] Do not move or rename source files in this task.
- [ ] Keep edits limited to Step 1 documentation artifacts and consistency fixes in planning docs if discovery proves them stale.

**Functionality (Expected Outcomes)**
- [ ] `step-01-audit.md` names all nine documented modules and their observed repository status.
- [ ] The audit records both the broad discovery scan and the policy-aligned boundary check.
- [ ] Root-level peer files are classified explicitly instead of being left ambiguous.
- [ ] Any mismatch between docs and code is called out directly instead of folded into later tasks.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `test -f docs/module-consolidation-3/step-01-audit.md`
- [ ] `rg "Repository Baseline|Verified Gap List|Consumer Inventory|Dependencies and Gates" docs/module-consolidation-3/step-01-audit.md`
- [ ] The audit output distinguishes the broad discovery scan from the enforced import-discipline check

---

## Task 2: Verify Which Planned Risks Still Exist

**Description**:
Turn the tranche risks from planning docs into a verified gap list. Each entry must say whether the issue still exists, what evidence supports that judgment, and why the issue matters for later consolidation.

**Implementation Plan (Do These Steps)**
- [ ] Add a `Verified Gap List` section to `docs/module-consolidation-3/step-01-audit.md`.
- [ ] Review the risk areas named in `plan.md`, `architecture.md`, and `clarifications.md`: public-interface leaks, runner decomposition follow-through, workflow/state boundary overlap, db/git access leakage, api/config ownership drift, and documented-import-rule mismatch.
- [ ] Create one row per candidate issue with these required fields:
  - `finding_id`
  - `status`
  - `evidence_type`
  - `exact_file_or_command`
  - `downstream_reason`
  - `affected_modules`
- [ ] Use only these statuses: `verified`, `not_found`, `docs_stale_code_ok`, `docs_code_conflict_stop`.
- [ ] For broad risks, do not allow `not_found` until a targeted search plan is recorded first.
- [ ] Treat `docs_code_conflict_stop` as an execution stop condition, not a passive note.

**Dependencies**
- [ ] Task 1 complete: `step-01-audit.md` exists and includes the repository baseline.

**References**
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)
- [clarifications.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/clarifications.md)

**Constraints**
- [ ] Every gap-list row must include exact evidence or an explicit targeted-search note.
- [ ] Do not mirror the planning docs as placeholder findings.

**Functionality (Expected Outcomes)**
- [ ] The gap list separates verified issues from disproven or stale assumptions.
- [ ] Each verified issue includes why it matters for later interface cleanup or domain refactors.
- [ ] Highest-signal repo conflicts such as import-rule mismatches are represented as explicit findings.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every row in `Verified Gap List` has a `finding_id` and one allowed status
- [ ] No issue in the gap list lacks exact evidence or a targeted-search note
- [ ] Any docs/code conflict is visibly marked as a stop condition

---

## Task 3: Inventory Consumers for Each Verified Issue

**Description**:
Bound the blast radius for later steps by recording who consumes each confirmed internal path or leaky boundary. Consumer coverage must include non-source callers, not just runtime code.

**Implementation Plan (Do These Steps)**
- [ ] Add a per-finding `Consumer Inventory` subsection for every `verified` finding in `docs/module-consolidation-3/step-01-audit.md`.
- [ ] For each verified finding, name the exact symbol, path, or rule being inventoried.
- [ ] Search the required roots for every verified finding:
  - `src/`
  - `tests/`
  - `scripts/`
  - `src/orchestrator/db/migrations/`
- [ ] Treat startup wiring as explicit file paths, at minimum:
  - `src/orchestrator/api/app.py`
  - `src/orchestrator/cli/main.py`
  - `scripts/serve.py`
  - `scripts/worker.py`
- [ ] If the finding changes import-policy interpretation, include `scripts/check_module_imports.py` as a policy-tooling consumer.
- [ ] Record caller categories even when empty, using `none_found` rather than omission.
- [ ] If a verified issue cannot be scoped to a bounded consumer set, record a blocker entry with:
  - `finding_id`
  - `why_scope_is_unbounded`
  - `blocked_step`
  - `next_required_action`

**Dependencies**
- [ ] Task 2 complete: the verified gap list exists.

**References**
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [docs/ARCHITECTURE.md](/Users/peter/code/task-world/worktrees/r51/docs/ARCHITECTURE.md)
- [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)

**Constraints**
- [ ] Consumer categories must include runtime code, tests, scripts, migrations, startup wiring, and policy tooling when relevant.
- [ ] Do not group the inventory only by file type; it must stay grouped by verified finding.

**Functionality (Expected Outcomes)**
- [ ] Every verified issue has a bounded consumer inventory or an explicit blocker.
- [ ] Startup entry points and migration callers are named concretely.
- [ ] Policy tooling is tracked when Step 1 findings affect enforcement logic.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Every `verified` finding includes consumer categories with explicit `none_found` where needed
- [ ] Startup wiring and migration roots are covered by name
- [ ] No verified issue proceeds without either a bounded inventory or a blocker record

---

## Task 4: Record Step Dependencies and Stop/Go Gates

**Description**:
Translate the audit results into execution gates for Steps 2-5. Later work must depend on findings from this step, not on general tranche narrative.

**Implementation Plan (Do These Steps)**
- [ ] Add a `Dependencies and Gates` section to `docs/module-consolidation-3/step-01-audit.md`.
- [ ] For every downstream step, map the exact `F-XX` findings it depends on:
  - Step 2: public export cleanup or canonical import decisions
  - Step 3: domain-refactor candidates and owning domain
  - Step 4: caller categories requiring dedicated sweep coverage
  - Step 5: tranche-wide proof rules and blocker ledger
- [ ] Define each stop condition with these required fields:
  - `trigger`
  - `required_doc_update`
  - `next_allowed_action`
  - `blocked_steps`
- [ ] If docs require correction, note that execution pauses until the affected planning files are updated consistently.

**Dependencies**
- [ ] Task 3 complete: verified issues have bounded consumer inventories or blocker notes.

**References**
- [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md)
- [step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-03-plan.md)
- [step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md)
- [step-05-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-05-plan.md)

**Constraints**
- [ ] Later steps must reference specific Step 1 finding IDs, not generic audit prose.
- [ ] Use the nested `steps/` path family consistently.

**Functionality (Expected Outcomes)**
- [ ] The Step 1 audit tells later builders when they may proceed and when they must stop.
- [ ] Each downstream step has named dependencies tied to explicit `F-XX` findings.
- [ ] Path-family drift is removed from the active execution docs.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `Dependencies and Gates` maps Steps 2-5 to specific `F-XX` findings
- [ ] Every stop condition includes trigger, required document update, next action, and blocked steps
- [ ] The nested `steps/` path family is the only downstream step reference used in the audit

---

## Task 5: Run Baseline Verification and Freeze the Audit Output

**Description**:
Validate that the Step 1 audit is evidence-backed and that the repository remains green before any refactor work starts. This is the final gate for the reality-audit step.

**Implementation Plan (Do These Steps)**
- [ ] Re-run the broad discovery scan and the policy-aligned import check after the audit notes are complete so the artifact reflects current repository state.
- [ ] Run the documented baseline unit test suite:
```bash
uv run pytest tests/unit -v
```
- [ ] Record one of exactly three outcomes for the baseline test gate:
  - `passed`
  - `failed_repository`
  - `blocked_environment`
- [ ] If the outcome is `blocked_environment`, capture the command, stderr, and the environment/tool reason in `step-01-audit.md`.
- [ ] Review `step-01-audit.md` and confirm every claimed issue is backed by evidence captured in Tasks 1-3.
- [ ] If the audit uncovered stale planning assumptions, update the relevant planning artifacts under `docs/module-consolidation-3/` before declaring this step complete.
- [ ] Freeze the audit by confirming:
  - the artifact exists at the named path
  - `F-XX` finding IDs are stable
  - dependency mapping is complete

**Dependencies**
- [ ] Tasks 1-4 complete.

**References**
- [intent.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/intent.md)
- [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md)
- [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md)

**Constraints**
- [ ] Do not begin source refactors in this task.
- [ ] If baseline verification does not pass or cannot execute, do not mark Step 1 complete without recording the explicit gate outcome.

**Functionality (Expected Outcomes)**
- [ ] The repository baseline checks are recorded and reproducible.
- [ ] `step-01-audit.md` is ready for direct citation by later steps.
- [ ] Any stale-doc mismatch is resolved in docs before refactor execution proceeds.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `step-01-audit.md` contains the baseline verification outcome and supporting command evidence
- [ ] The final Step 1 audit distinguishes verified issues from stale assumptions and includes dependency notes
- [ ] Later builders can identify a stop/go decision for Step 2 directly from the Step 1 audit
