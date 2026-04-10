# Dry Run Notes: Step 1 Reality Audit and Gap List

This note simulates execution of [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-01-plan.md) against the live repository. It is analysis only. No source changes are proposed here.

## Live Repository Checks Used For This Dry Run

- The nine documented public packages exist under `src/orchestrator/`: `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, and `workflow`.
- Root-level peer modules also exist under `src/orchestrator/` and need explicit classification during execution because they can look like public entry points or shims:
  - [executor.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/executor.py)
  - [errors.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/errors.py)
  - [time_utils.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/time_utils.py)
  - [__version__.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/__version__.py)
- There are two step-plan path families in the repo:
  - top-level: [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-plan.md) through [step-05-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-05-plan.md)
  - nested: [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-01-plan.md) through [step-05-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-05-plan.md)
- The repository already has an enforcement script for the documented module-boundary rule:
  - [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
- That script does not forbid all `orchestrator.<module>.<something>` imports. It forbids cross-module imports that reach into another module's sub-package directory. Root-file imports such as `from orchestrator.config.models import ...` remain allowed.
- The sample command in the step file currently produces high-noise output in this repo because it matches same-module imports and allowed cross-module root-file imports:
  - `rg "from orchestrator\\.[^.]+\\.|import orchestrator\\.[^.]+\\." src tests`
- The consumer inventory search space is broader than `src/` and `tests/`. Relevant non-source callers exist in:
  - [scripts](/Users/peter/code/task-world/worktrees/r51/scripts)
  - [migrations env.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/env.py)
  - [migrations/versions](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/versions)
  - startup entry points such as [app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py), [main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py), [serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py), and [worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py)
- `uv run pytest tests/unit -v` could not be validated in this sandbox. `uv` first hit cache permission problems under `~/.cache/uv`, then panicked even with `UV_CACHE_DIR` redirected into `/tmp`.

## Cross-Cutting Gaps In The Step File

- The step never names the canonical Step 1 audit artifact path. "Create or update the Step 1 audit artifact under `docs/module-consolidation-3/`" is ambiguous in a directory that already contains intent, plan, architecture, top-level step docs, nested step docs, and dry-run notes.
- The step assumes a generic grep can stand in for the actual module-boundary rule. In this repository, that grep is only a noisy evidence sample.
- The step references later step files using the top-level path family while the active input lives in the nested `steps/` path family.
- Several verification bullets prove the existence of the input step file instead of the created audit output.
- The step has no stable finding-ID scheme, so later steps can cite "the audit" without any precise dependency wiring.
- The step has no explicit blocked state for tool-environment failures during `uv run pytest`.

## Task 1: Confirm the Nine-Module Baseline Against the Repository Layout

### Assumptions

- The builder knows which file is the Step 1 audit artifact.
- The nine-module baseline can be established by checking `src/orchestrator/<module>/__init__.py`.
- "Unexpected peer package appears to act like a public entry point" is sufficient to catch real boundary ambiguity.
- The broad grep output is interpretable as a useful baseline.

### Expected Outputs

- A `Repository Baseline` section in the Step 1 audit artifact.
- A list of all nine documented public modules with observed package status.
- A note covering root-level peer modules and whether they act as public surface, shim, or internal utility.
- A reproducible import-scan command and summarized findings.
- A stop/go note if code reality materially contradicts the docs.

### Blockers

- No canonical output path is specified for the Step 1 audit artifact.
- "Materially contradicts" is subjective and not operationally defined.
- The grep command is too broad to distinguish allowed imports from policy violations.
- The task asks about unexpected peer packages, but the live ambiguity is mainly root-level peer files.

### Failure Modes

- File-reference mismatch:
  - A builder can update [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-01-plan.md) or [step-01-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-01-plan.md) instead of creating a separate audit note.
- Create-vs-update ambiguity:
  - The task says "Create or update" without naming the target file, so builders can produce incompatible artifacts in different locations.
- False positives from import scan:
  - The live grep matches same-module imports, `__init__.py` re-exports, and allowed root-file imports. It is not a direct forbidden-import check.
- Root-level entry-point ambiguity omitted:
  - [executor.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/executor.py) is a backwards-compatible shim, but the task only asks about peer packages.
- Verification proves the wrong thing:
  - `test -f docs/module-consolidation-3/steps/step-01-plan.md` only proves the input exists.

### Concrete Hardening Actions

- Require a single output path, for example `docs/module-consolidation-3/step-01-audit.md`.
- Define "material contradiction" explicitly:
  - missing documented package
  - extra package acting as public entry point
  - root-level peer file acting as public surface or shim
  - mismatch between documented import rule and enforced import rule
- Split the import evidence into two passes:
  - broad baseline sample for discovery
  - policy-aligned scan using [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
- Add a required classification table for root-level `src/orchestrator/*.py` files.

## Task 2: Verify Which Planned Risks Still Exist

### Assumptions

- The risk areas from `plan.md`, `architecture.md`, and `clarifications.md` can each be verified or disproven from live code.
- Labels `verified`, `not found`, and `needs doc correction` are enough to drive later execution.
- A builder will gather evidence rather than restating the planning docs.

### Expected Outputs

- A `Verified Gap List` section in the audit artifact.
- One row per candidate issue with status, evidence, and why it matters.
- Visible stale-assumption markings for disproven issues.

### Blockers

- Several risks are too broad to query without a narrower evidence plan:
  - runner decomposition follow-through
  - workflow/state boundary overlap
  - db/git access leakage
  - api/config ownership drift
- The step does not define what counts as sufficient evidence.
- `needs doc correction` is underspecified operationally.

### Failure Modes

- Placeholder gap list:
  - A builder can mirror the planning risks without enough live evidence.
- Inconsistent evidence quality:
  - Some rows can cite exact files while others only say "observed in codebase."
- Premature `not found`:
  - Broad risks can be dismissed without a targeted search plan.
- `needs doc correction` hides stop conditions:
  - The same label can mean either "docs stale but harmless" or "docs and code conflict; execution must pause."
- Highest-signal mismatch omitted:
  - The gap list can miss the conflict between the broad grep in the step and the actual rule in [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py).

### Concrete Hardening Actions

- Require every gap row to include:
  - status
  - evidence type
  - exact file path or exact command
  - why the issue matters downstream
- Define minimum evidence by issue type:
  - import leakage: concrete search hits
  - export gap: symbol missing from module `__init__.py`
  - ownership drift: concrete import direction or file-placement mismatch
- Require a targeted search plan before allowing `not found` for a broad risk.
- Split `needs doc correction` into:
  - docs stale, code acceptable
  - docs/code conflict, stop required
- Add a required risk row for "documented import rule vs enforced import rule mismatch."

## Task 3: Inventory Consumers For Each Verified Issue

### Assumptions

- Every verified issue can be reduced to a bounded symbol, path, rule, or surface.
- All relevant consumers are discoverable by repository search.
- "Startup wiring" is understood well enough to search consistently.

### Expected Outputs

- A per-issue `Consumer Inventory` subsection.
- Coverage for runtime code, tests, scripts, migrations, and startup wiring.
- A blocker note when scope cannot be bounded.

### Blockers

- The step does not define search roots for `scripts/` or migrations.
- "Startup wiring" is not specified.
- Some findings may concern policy or ownership, not a single symbol.
- If the import rule itself changes, the enforcement script becomes a consumer but the step does not say to check it.

### Failure Modes

- Consumer coverage too narrow:
  - A builder can search only `src/` and `tests/`, missing [serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py), [worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py), [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py), and migration files.
- Startup wiring omitted:
  - The step does not name live entry points such as [app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py), [main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py), [serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py), and [worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py).
- Unbounded issue left as TODO:
  - The task says this becomes a blocker but does not require a blocker format.
- Consumer inventory grouped the wrong way:
  - A builder can produce file-type buckets instead of issue-by-issue blast radius.
- Policy consumer omitted:
  - If a finding changes how import discipline is interpreted, [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py) can stay stale and later verification will still use the old rule.

### Concrete Hardening Actions

- Define search roots explicitly:
  - `src/`
  - `tests/`
  - `scripts/`
  - `src/orchestrator/db/migrations/`
- Define startup wiring explicitly with live entry points.
- Require each verified issue to name the exact symbol, path, or rule being inventoried.
- Require blocker entries to include:
  - finding ID
  - why scope is unbounded
  - which later step is blocked
- Treat policy tooling as a consumer whenever a finding affects import enforcement.

## Task 4: Record Step Dependencies And Stop/Go Gates

### Assumptions

- Later step files already exist and are stable enough to cite directly.
- Verified issues can be mapped cleanly onto Steps 2-5.
- A single Step 1 artifact can become the authoritative downstream dependency source.

### Expected Outputs

- A `Dependencies and Gates` section in the Step 1 artifact.
- Step-specific dependency notes for Steps 2-5.
- Explicit stop/go criteria for stale docs, contradictory ownership, and unbounded consumers.

### Blockers

- The step references top-level step files while the active step file lives in the nested `steps/` path family.
- No stable finding IDs are required.
- The step does not require later step docs to consume the dependency output.

### Failure Modes

- Downstream references stay ambiguous:
  - Later builders can cite "the Step 1 audit" without a finding key.
- Wrong path family cited:
  - One builder can use [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-plan.md) while another uses [step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md).
- Stop/go rules too generic:
  - "stale-doc mismatch" can be recorded without naming which document must be updated.
- Planning wiring not activated:
  - Step 1 can be accurate while Steps 2-5 still proceed from generic tranche narrative rather than explicit findings.

### Concrete Hardening Actions

- Assign stable finding IDs such as `F-01`, `F-02`, and require all later dependencies to cite them.
- Declare one canonical path family for step-plan files.
- Require each stop condition to include:
  - trigger
  - required doc update
  - next allowed action
- Add a completion check that later step notes or later step docs reference Step 1 finding IDs before Step 1 is treated as closed.

## Task 5: Run Baseline Verification And Freeze The Audit Output

### Assumptions

- `uv run pytest tests/unit -v` is runnable in the current environment.
- Documentation-only changes will not invalidate the import scan.
- If stale assumptions are found, the builder can update planning docs in the same step without causing drift.

### Expected Outputs

- Re-run import sample recorded in the artifact.
- Baseline unit-test result captured.
- Final audit wording fixed for later citation.
- Any stale-plan mismatch corrected before Step 1 is closed.

### Blockers

- In this sandbox, `uv run pytest tests/unit -v` did not reach test execution because of `uv` runtime/cache issues.
- The step has no explicit way to distinguish repository regressions from environment-tool failures.
- "Freeze the final wording" is not itself a verifiable repository state.

### Failure Modes

- Test failure with no recovery rule:
  - The step only says Step 1 is incomplete if tests fail.
- Tooling failure misreported as code failure:
  - A builder can report a repository regression when the actual problem is `uv` environment behavior.
- Audit output not really frozen:
  - Without a named artifact path and stable finding IDs, later steps can reinterpret the results.
- Planning docs updated inconsistently:
  - The task says to update the relevant planning artifact, but does not require consistency across [intent.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/intent.md), [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md), and [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md).

### Concrete Hardening Actions

- Add an explicit blocked outcome for baseline test-command failures caused by environment or tool behavior, with captured command output.
- Distinguish three outcomes for the baseline test gate:
  - tests pass
  - tests fail
  - tests could not execute because of environment/tool failure
- Define "freeze" operationally:
  - audit artifact exists at a named path
  - finding IDs are stable
  - dependency mapping is complete
- If any planning doc changes in Task 5, require a consistency pass across [intent.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/intent.md), [plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md), and [architecture.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/architecture.md).

## File Reference, Interface, And Wiring Checks

- File references used by the step are mostly real, but the path family for later step docs is inconsistent.
- The step uses "create or update" language without naming the audit artifact path, so file-target ambiguity is real.
- No model, class, protocol, adapter, handler, persistence field, or schema is introduced by this step.
  - No DB column work is required.
  - No repository read/write completeness issue exists here.
  - No async wiring gap exists here.
  - No integration-test assertion updates are inherently required by Step 1 itself.
- Component wiring in the runtime sense is not applicable here because Step 1 is documentation-only.
- Planning wiring is applicable and currently under-specified:
  - later steps must replace generic tranche references with specific Step 1 finding IDs
  - later verification must use the import-discipline rule that Step 1 proves
  - otherwise the new audit output can exist while the active execution path still follows the old narrative

## Highest-Value Hardening Actions Before Real Execution

1. Name the Step 1 audit artifact file explicitly.
2. Align import verification with [check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py), or explicitly declare that the tranche is changing that rule.
3. Pick one canonical step-doc path family and use it everywhere.
4. Require stable finding IDs and dependency references to those IDs.
5. Replace verification bullets that only prove the input step file exists.
6. Define search roots and startup-wiring examples for consumer inventory.
7. Add a blocked outcome for `uv`/environment failures in the baseline test gate.
