# Step 5 Dry-Run Notes

Scope: analysis of [step-05-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-05-plan.md) against the live repository. No step files or source files were modified.

## Repo-grounded observations

- The input file exists at [docs/module-consolidation-3/steps/step-05-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-05-plan.md).
- The requested output file did not exist before this run, so `docs/module-consolidation-3/dry-run/step-05-plan-notes.md` needed creation, not update.
- The repo has both root-level planning files and `steps/` copies. Step 5 mixes those paths:
  - task references point to [docs/module-consolidation-3/steps/step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-02-plan.md), [docs/module-consolidation-3/steps/step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-03-plan.md), and [docs/module-consolidation-3/steps/step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md)
  - the corresponding step plan block points to [docs/module-consolidation-3/step-02-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-02-plan.md), [docs/module-consolidation-3/step-03-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-03-plan.md), and [docs/module-consolidation-3/step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/step-04-plan.md)
- The repo contains real operational caller categories relevant to this step:
  - tests under `tests/`
  - scripts under `scripts/`
  - migrations under [src/orchestrator/db/migrations/](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/)
  - CLI startup at [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py)
  - API startup at [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py)
- The proposed import-audit regex is not repository-safe as written. Live results include:
  - same-module internal imports under `src/orchestrator/...`
  - root-package compatibility wrappers such as [src/orchestrator/config/loader.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/config/loader.py), [src/orchestrator/runners/openhands.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/runners/openhands.py), and [src/orchestrator/runners/codex_server.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/runners/codex_server.py)
  - comment/example hits in [scripts/check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
  - direct `import orchestrator...` hits only if a second regex is added
- There are real non-source caller imports today, for example:
  - [tests/integration/test_routine_loading.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_routine_loading.py)
  - [tests/integration/test_api_agent_configs.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_api_agent_configs.py)
  - [tests/integration/test_project_routines.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_project_routines.py)
  - [tests/integration/test_mcp_server.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_mcp_server.py)
  - [tests/unit/test_prune_ops.py](/Users/peter/code/task-world/worktrees/r51/tests/unit/test_prune_ops.py)
- No new classes, protocols, adapters, handlers, schema fields, or persistence models are introduced by this step. The main wiring risk is false proof: the system can still be using old import paths or compatibility wrappers while the final notes claim the tranche is complete.

## Cross-cutting failure modes

- The step assumes Steps 2 through 4 leave behind a canonical import map and touched-caller inventory, but it does not require a specific artifact schema for either one.
- The import audit is underspecified for the repo’s actual structure:
  - it searches `src`, which mixes implementation internals with external-caller proof
  - it omits direct `import orchestrator...` forms unless the operator expands it manually
  - it does not name exclusions for comments, examples, or root-package compatibility wrappers
- "Touched operational callers" is not concrete enough to guarantee consistent execution. The repo has identifiable startup and script entry points, but the step does not require them by file path.
- The final verification matrix mentions additional shared-contract or startup smoke checks, but does not require earlier steps to name them in executable form.
- The temporary-structure audit has no concrete search pattern or checklist schema, so it can devolve into a subjective scan.
- Completion-note mapping is not format-defined. Without a required table or checklist, intent coverage can become prose that is hard to verify.

## Task 1: Rebuild the Final Proof Scope From Prior Steps

### Assumptions

- Steps 2, 3, and 4 produced explicit artifacts naming canonical public imports, forbidden internal paths, and touched caller categories.
- The tranche plan plus earlier step artifacts are enough to reconstruct final-proof scope without reopening discovery.
- A "final-proof checklist" either already exists or can be written without an agreed schema.

### Expected outputs

- A final-proof checklist tied to actual earlier-step outputs.
- A list of exact source areas, caller categories, commands, and boundary rules to audit.
- A stop condition if prior artifacts are too vague.

### Blockers and mitigation

- Blocker: earlier steps do not expose a canonical import map in a reusable format.
  - Mitigation: require Step 2 output to list `canonical_import`, `obsolete_import_prefix`, `affected_module`, and `consumer_categories`.
- Blocker: touched caller categories are only described narratively.
  - Mitigation: require Step 4 output to include exact file paths or glob patterns by category.
- Blocker: the checklist has no required location or schema.
  - Mitigation: require a single checklist section in the Step 5 notes with fixed fields: `area`, `caller_category`, `expected_rule`, `command`, `source_artifact`.

### Failure modes

- File references are inconsistent between `steps/` and root-level step-plan files.
- "Write or update" is ambiguous against the requested output path. In this repo the Step 5 output file does not exist yet, so the action must be `create`.
- The step does not define what proves that the verification matrix was "defined before any audit command is treated as evidence".
- Existing tests can still pass even if the final-proof checklist is incomplete, because this task is mostly scoping and documentation.

### Hardening actions

- Require Task 1 to fail unless the checklist includes:
  - canonical import prefixes
  - forbidden import prefixes
  - exact caller categories and paths
  - exact `uv run` commands
  - earlier-step artifact references
- Require the step to use one reference namespace consistently: either `steps/` artifacts or root-level plan files, not both.
- Require the note to say `create final-proof checklist` if the file is absent.

## Task 2: Run the Repository-Wide Import-Discipline Audit

### Assumptions

- The tranche-targeted forbidden-import rules are specific enough to translate into exact search patterns.
- Search results can be classified reliably into allowed same-module usage, false positives, and blockers.
- Searching `src tests scripts` is sufficient to cover source and operational callers.

### Expected outputs

- A classified audit result for source and non-source callers.
- Exact blocking file paths for any forbidden import.
- A hard stop before verification if blockers remain.

### Blockers and mitigation

- Blocker: the regex is broader than the step’s stated goal and returns many same-module internal hits.
  - Mitigation: split the audit into separate searches:
    - external callers: `tests`, `scripts`, migration files, specific startup files
    - source-internal proof only for known startup/entry modules
- Blocker: the regex misses `import orchestrator.module.submodule` forms.
  - Mitigation: require both `from ... import ...` and `import ...` search patterns.
- Blocker: comments and examples pollute results.
  - Mitigation: require explicit classification rules and exclude documentation-like matches when counting blockers.

### Failure modes

- The provided command searches `src`, which overwhelms the operator with allowed same-module imports and package-internal re-exports.
- The step says "operational callers" but the command does not include the migration directory explicitly as its own category or specific startup entry files.
- The current repo contains root-package wrappers and re-exports that may be temporary or intentional. The step does not say how to classify those.
- Component wiring risk: because there are no new components here, the real failure mode is that the active API/CLI/script entry points still use old paths or wrappers while the audit is declared clean based on narrower searches.

### Hardening actions

- Replace the single broad command with category-specific commands:
  - `tests/**/*.py`
  - `scripts/**/*.py`
  - [src/orchestrator/db/migrations/env.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/env.py) and `versions/*.py`
  - [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py)
  - [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py)
- Require both import forms in the audit:
  - `from orchestrator...`
  - `import orchestrator...`
- Require every match to be logged with `file`, `match`, `classification`, and `reason`.

## Task 3: Execute the Final Verification Matrix

### Assumptions

- `uv run pytest`, `uv run pyright`, and `uv run ruff check .` are the minimum final-proof suite.
- Earlier steps already defined any additional shared-contract or startup checks needed for touched domains.
- Repository-wide verification is feasible after the audit is clean.

### Expected outputs

- Recorded results for the repo-wide test, type, and lint commands.
- Recorded results for any extra touched-domain checks.
- A reopen decision if any command fails.

### Blockers and mitigation

- Blocker: earlier steps may never have named additional startup or shared-contract checks.
  - Mitigation: Task 1 must surface them explicitly or block Task 3.
- Blocker: repo-wide commands may pass while active startup paths are still stale if no startup smoke check is run.
  - Mitigation: require concrete startup checks for touched domains, not just "if needed" prose.
- Blocker: zero-test collection or broad skips can make `pytest` look green without proving touched behavior.
  - Mitigation: require final notes to record suite summary counts and any skip-heavy areas relevant to touched domains.

### Failure modes

- The step does not name what "shared-contract or startup smoke checks" actually are.
- It does not require recording command output in a structured way, so reruns and remediation evidence may be lost.
- Existing tests can still pass without proving active entry-point wiring if final proof stops at generic automation.
- No async or infrastructure dependency is introduced by this step, but the verification plan may still miss startup wiring that depends on real runtime initialization.

### Hardening actions

- Require Task 3 notes to capture, per command:
  - exact command
  - pass/fail
  - rerun count
  - reason for rerun
- Require startup checks when the tranche touched API, CLI, runners, or workflow entry surfaces.
- Require final notes to include pytest collection/result summary, not just "passed".

## Task 4: Confirm No Temporary Structure or Deferred Cleanup Remains

### Assumptions

- Earlier steps recorded any temporary re-exports, duplicate trees, or deferred cleanup items if they existed.
- A manual scan of touched domains is enough to prove structural completeness.

### Expected outputs

- Explicit confirmation that no temporary structure remains, or a reopen note tied to an earlier step.
- Evidence that no deferred cleanup survived into final sign-off.

### Blockers and mitigation

- Blocker: no concrete definition of "temporary structure" is provided for this repo.
  - Mitigation: require the check to include at least:
    - compatibility wrapper modules
    - duplicate public paths for the same symbol
    - TODO/remove-later cleanup notes tied to the tranche
- Blocker: no concrete artifact proves the earlier-step deferred-cleanup state.
  - Mitigation: require Step 3 and Step 4 outputs to include an explicit `deferred_cleanup_items: none` or enumerated list.

### Failure modes

- The step does not specify how to inspect for compatibility shims or duplicate trees.
- Root-level wrappers already exist in the repo. Without an explicit tranche-owned list, the operator cannot tell whether they are legacy debt, intentional API surfaces, or blockers created by this tranche.
- The task can be marked green based on subjective judgment rather than explicit evidence.
- Component wiring risk: a compatibility wrapper can keep the active path working, so generic tests pass while the tranche still violates its no-shims rule.

### Hardening actions

- Require Task 4 to check and log:
  - any module added as a top-level compatibility bridge
  - any symbol exported from two public paths
  - any file or comment containing tranche-owned deferred cleanup markers
- Require the earlier steps to maintain a tranche-owned "temporary structure ledger" so Task 4 can prove it is empty.

## Task 5: Record Completion Notes and Reopen Earlier Steps on Any Failure

### Assumptions

- The tranche intent can be mapped cleanly to earlier steps and final-proof evidence.
- Out-of-scope items remain exactly the ones named in the tranche intent.
- A short final note is enough to prove intent coverage.

### Expected outputs

- Completion notes that map covered intent items to completed steps.
- A release-ready conclusion only if Tasks 1 through 4 are green.
- A reopen note naming the failed proof and owning earlier step if anything failed.

### Blockers and mitigation

- Blocker: the step does not define the mapping format for intent coverage.
  - Mitigation: require a table with `intent_id`, `owning_step`, `evidence`, `status`.
- Blocker: no rule says how to handle intent items already marked `NO-REQ`.
  - Mitigation: require a separate out-of-scope section sourced directly from [intent.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/intent.md), not inferred ad hoc.

### Failure modes

- The note can claim coverage without pointing to actual earlier-step artifacts.
- "Release-ready" can become a prose conclusion with no hard dependency on the Task 1 to 4 evidence block.
- If final proof fails, the step does not require a standard reopen record layout, so the retry path may be unclear.
- No persistence-layer change is involved here, but the note could still omit a blocker tied to migrations or startup callers if the earlier audit never surfaced them.

### Hardening actions

- Require Task 5 to include:
  - `intent item -> step -> evidence` mapping
  - `out of scope` section copied from the tranche intent
  - `final status` with only `release_ready` or `reopen_required`
  - `reopen owner step` and `blocking proof` when not green

## Specific failure-mode answers

### Are file references correct?

- Partially. The main input/output paths are correct.
- The step references are inconsistent between `docs/module-consolidation-3/steps/...` and `docs/module-consolidation-3/...`.
- The operational caller references are incomplete unless migrations and specific startup files are called out explicitly.

### Are model/class names correct against actual source?

- No new model or class names are introduced by this step.
- The risky names are artifact names, not code symbols: "canonical import map", "final-proof checklist", and "completion notes" are not defined as concrete file sections or schemas.

### Does "create" vs "update" match file existence?

- No for the requested output file. [docs/module-consolidation-3/dry-run/step-05-plan-notes.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/dry-run/step-05-plan-notes.md) did not exist before this run, so the action should be `create`.
- Ambiguous for the "final-proof checklist" because the step does not name its file or section.

### Are format-dependent interfaces specified explicitly?

- No. The checklist, audit log, temporary-structure proof, and completion-note mapping all need explicit schemas.

### Will existing tests break?

- The step itself does not change code, so this dry run does not introduce breakage.
- As an execution plan, it can miss stale imports in active callers while the generic suite still passes, producing a false green.

### Are async/infrastructure dependencies resolved?

- No new async or infrastructure component is introduced here.
- Startup and runtime wiring checks are underspecified, which is the practical infrastructure risk.

### Persistence layer complete?

- Not applicable for this step. No DB columns, repository writes, or repository reads are added.
- The audit still needs explicit migration-file coverage because persistence callers may be part of the forbidden-import surface.

### Integration test assertions specified?

- Not adequately. The step requires repo-wide `pytest` plus unspecified shared-contract/startup checks, but it does not say which integration flows prove touched domains still load through the public module surface.

### Component wiring verified?

- No. There are no new components to wire in, but there is no explicit requirement to exercise the active API, CLI, and script entry points that would prove the repo is actually using the canonical paths after the tranche.

## Recommended hardening summary

- Standardize all step references on one path namespace.
- Require Task 1 to output a structured final-proof checklist before any audit or verification command counts as evidence.
- Split Task 2 audits by caller category and require both `from ...` and `import ...` patterns.
- Name the active entry points explicitly:
  - [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py)
  - [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py)
  - [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py)
  - [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py)
  - [src/orchestrator/db/migrations/env.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/env.py)
- Require Task 3 to record structured command results and startup smoke checks for touched domains.
- Require Task 4 to prove the tranche-owned temporary-structure ledger is empty.
- Require Task 5 to use a structured intent-coverage table and a single final status field.
