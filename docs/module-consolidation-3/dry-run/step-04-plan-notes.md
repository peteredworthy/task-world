# Step 4 Dry-Run Notes

Scope: analysis of [step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md) against the live repository. No step files or source files were modified.

## Repo-grounded observations

- The input file exists at [docs/module-consolidation-3/steps/step-04-plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/steps/step-04-plan.md). The referenced sibling planning docs also exist.
- The requested output path did not exist yet; `docs/module-consolidation-3/dry-run/` was missing before this note was created.
- The repo has real non-source caller categories for this step:
  - tests under `tests/`
  - scripts under `scripts/`
  - migrations under [src/orchestrator/db/migrations/](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/)
  - CLI startup at [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py)
  - API startup at [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py)
  - operational entry points at [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py) and [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py)
- The proposed `rg` pattern currently returns many false positives for this step:
  - same-module internal imports under `src/orchestrator/...`
  - root-package implementation imports that are not non-source callers
  - duplicated matches caused by searching both `src/orchestrator` and `src`
  - string/documentation examples in [scripts/check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py)
- There are real external-caller hits today, for example:
  - [tests/integration/test_routine_loading.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_routine_loading.py)
  - [tests/integration/test_api_agent_configs.py](/Users/peter/code/task-world/worktrees/r51/tests/integration/test_api_agent_configs.py)
  - multiple other tests importing `orchestrator.config.routines.*`, `orchestrator.runners.profiles.*`, `orchestrator.api.mcp.*`, and `orchestrator.git.ops.*`

## Cross-cutting gaps

- The step says "non-source callers" but repeatedly searches `src/orchestrator` broadly. That mixes implementation-internal imports with the caller sweep and will drown the operator in irrelevant matches.
- The step relies on "actual module names from the finished refactor" but does not require the completed Step 3 batch to name those modules explicitly. That makes the sweep hard to scope.
- "Operational tooling" is not enumerated concretely. In this repo it should at least include [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py), [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py), [scripts/seed_db.py](/Users/peter/code/task-world/worktrees/r51/scripts/seed_db.py), [scripts/restore_from_journal.py](/Users/peter/code/task-world/worktrees/r51/scripts/restore_from_journal.py), and [scripts/check_module_imports.py](/Users/peter/code/task-world/worktrees/r51/scripts/check_module_imports.py).
- The verification commands are not format-aware enough:
  - `uv run python -c "import path.to.updated_script_module"` only works for importable Python modules, not shell scripts or scripts whose behavior lives under `if __name__ == "__main__"`.
  - plain import smoke checks may not exercise startup wiring that is only used at runtime.
- No new classes or adapters are introduced in this step, so the main wiring risk is not "unused new code". The real risk is that old startup and test call sites remain on internal imports while Step 3 changes appear green through unaffected code paths.

## Task 1: Refresh the Consumer Sweep Scope

### Assumptions

- Step 3 completion notes exist in a form that names the finished domain batch precisely enough to scope the sweep.
- Step 1 and Step 2 artifacts contain a usable consumer inventory and canonical import map for that exact batch.
- The regex is sufficient to find obsolete imports for the batch.
- Caller categories can be derived from search results without an explicit source-of-truth checklist format.

### Expected outputs

- A current checklist for one completed Step 3 batch.
- Categorized `rg` matches: same-module allowed, external caller to migrate, false positive.
- A stop condition if Step 1 or Step 2 drifted.

### Blockers and mitigation

- Blocker: Step 3 notes do not identify the exact symbols/modules changed.
  - Mitigation: require the Step 3 batch note to include `affected_modules`, `obsolete_paths`, and `canonical_paths`.
- Blocker: Step 1 inventory is incomplete for tests/scripts/migrations/startup.
  - Mitigation: refresh the inventory before any Task 2 inspection starts.
- Blocker: the search command returns too many irrelevant matches to classify reliably.
  - Mitigation: run module-scoped searches only for the completed batch and exclude source-internal paths unless they are startup entry points.

### Failure modes

- File references: correct for Step 1/2/3 docs, but the step omits the actual migration directory path.
- Search pattern is wrong for the stated goal:
  - includes `src/orchestrator` implementation internals
  - includes `src`, causing duplicates
  - ignores direct `import orchestrator.x.y.z` forms
  - treats string examples as hits if the operator falls back to plain grep review
- Output format is underspecified: "write or update a short working checklist" does not say where it lives or what fields it must contain.
- Existing tests can still pass even if the checklist is incomplete, because this task is mostly documentation and search triage.

### Hardening actions

- Require the completed Step 3 batch note to provide:
  - affected top-level module
  - symbols moved or re-exported
  - obsolete import prefixes
  - canonical import prefixes
- Narrow the search to caller categories first, for example:
  - `tests/**/*.py`
  - `scripts/**/*.py`
  - [src/orchestrator/db/migrations/](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/)
  - specific startup modules instead of all `src/orchestrator`
- Require both forms in searches:
  - `from orchestrator...`
  - `import orchestrator...`
- Require the checklist schema to include:
  - file path
  - caller category
  - current import
  - canonical import
  - status
  - note

## Task 2: Inspect Tests and Operational Callers Category by Category

### Assumptions

- Task 1 produced an exact caller list by category.
- Each caller can be classified by static inspection before edits.
- Running a single file-path pytest command is enough to validate a touched test caller.
- CLI/API startup wiring is captured by inspecting import-time modules and entry points.

### Expected outputs

- Per-category inspection notes with exact file paths.
- Migration set for Task 3.
- Early blocker identification for callers that need more than import rewrites.

### Blockers and mitigation

- Blocker: startup path is broader than import-time modules.
  - Mitigation: require concrete entry points: [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py), [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py), [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py), [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py).
- Blocker: migration callers are easy to miss because they live under `src/orchestrator/db/migrations/`.
  - Mitigation: explicitly scan [src/orchestrator/db/migrations/env.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/env.py) and `versions/*.py` if the Step 3 batch touched `db` or `runners.profiles.models`.
- Blocker: tests may import old paths that still work because root `__init__.py` exports also exist.
  - Mitigation: classify by import path, not by whether tests are green before migration.

### Failure modes

- Caller categories are correct in principle, but "operational tooling" remains vague and will cause inconsistent sweeps.
- The task does not require exact command capture for each inspected caller, only for tests.
- `uv run pytest path/to/known_test_file.py -v` is good for tests but does nothing for scripts, migrations, or startup entry points.
- Component wiring risk: if Step 3 changed canonical exports, Task 2 can still miss the active entry point using the old path because "startup wiring" is not tied to concrete files or commands.

### Hardening actions

- Require category-specific checklists:
  - tests: exact files and relevant assertions
  - scripts: exact module/script paths and invocation style
  - migrations: exact files under [src/orchestrator/db/migrations/](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/)
  - startup: exact entry point files and load commands
- Require one recorded validation command per inspected caller when feasible.
- Add a mandatory "active path" row for:
  - API app factory
  - CLI entry point
  - server script
  - worker script

## Task 3: Migrate Remaining High-Risk Callers

### Assumptions

- Step 2 already defined every canonical import needed for these callers.
- Replacing imports is sufficient; no behavior changes or export additions remain.
- Small edit batches plus import smoke tests keep the repo runnable.

### Expected outputs

- Updated non-source callers using top-level module imports.
- Per-batch verification.
- No obsolete imports left in the inventoried caller set for the completed domain batch.

### Blockers and mitigation

- Blocker: a caller needs a missing top-level export.
  - Mitigation: stop and reopen Step 2, do not patch around it in Step 4.
- Blocker: import replacement changes runtime behavior because the top-level export differs from the old symbol.
  - Mitigation: require behavior-oriented verification for each caller class, not just import success.
- Blocker: script or startup modules have side effects and import smoke either fails spuriously or passes without exercising the relevant path.
  - Mitigation: use command forms matching the entry point.

### Failure modes

- The `python -c "import ..."` examples are too weak for real callers:
  - [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py) does substantial work only when executed as `__main__`
  - [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py) performs startup guards at import time, but import alone does not prove the app boots correctly
  - Alembic environment wiring is not exercised by plain module import
- Search command still suffers from overbreadth and duplicates.
- Existing tests may still pass without verifying the changed caller is on the active path.
- Component wiring risk: if a startup script or entry point still imports the old internal path, updated helper tests can pass while production startup remains stale.

### Hardening actions

- Replace generic smoke examples with caller-specific verification patterns:
  - tests: `uv run pytest exact_test_file.py -v`
  - CLI: `uv run python -m orchestrator.cli.main --help`
  - API: `uv run python -c "from orchestrator.api import create_app; create_app(db_path=':memory:', routine_dirs=[]); print('ok')"`
  - server script: `uv run python -c "import scripts.serve; assert scripts.serve.app is not None; print('ok')"`
  - worker script: `ORCHESTRATOR_DB=/tmp/step4.db uv run python -c "import scripts.worker; print('ok')"`
  - migrations: `uv run alembic -c alembic.ini upgrade head`
- Require each migrated caller batch to list:
  - exact files changed
  - exact canonical imports adopted
  - exact verification commands run
- Add explicit acceptance rule: no caller batch is complete until the active entry point using that import path has been exercised.

## Task 4: Record and Escalate Blockers

### Assumptions

- Operators will consistently stop the milestone instead of leaving TODOs.
- There is an agreed place to record blockers and a status field that can mark the step as stopped.

### Expected outputs

- Blocker notes with path, obsolete import, target import, reason, and prior-step artifact to revisit.
- A stopped milestone state when any unresolved caller exists.

### Blockers and mitigation

- Blocker: no single blocker artifact location is named.
  - Mitigation: require a concrete blocker record location for this tranche.
- Blocker: "update those planning artifacts before the next attempt" is directionally right but does not say which file to update first.
  - Mitigation: tie blocker type to owning artifact:
    - inventory problem -> Step 1
    - canonical import problem -> Step 2
    - unfinished boundary refactor -> Step 3

### Failure modes

- The task does not name the blocker file or section, so notes can be scattered or lost.
- "Stop the milestone" is process language only; no explicit status artifact is required.
- If blockers are recorded outside the current batch note, later operators may not discover them before retrying.

### Hardening actions

- Require a single blocker log location for this tranche and batch.
- Require a batch status field with one of:
  - complete
  - stopped_blocked
- Require each blocker to include owner step and restart condition.

## Task 5: Capture Recurring Merge-Gate Checks

### Assumptions

- The sweep will produce reusable commands rather than one-off local fixes.
- The next batch will have similar caller categories.

### Expected outputs

- A short recurring merge-gate note.
- Updated tranche planning artifact if the sweep exposed a missing recurring gate.

### Blockers and mitigation

- Blocker: the step does not specify where the recurring note lives.
  - Mitigation: require either [docs/module-consolidation-3/plan.md](/Users/peter/code/task-world/worktrees/r51/docs/module-consolidation-3/plan.md) or a dedicated recurring-gates section/file for Step 4 outputs.
- Blocker: commands may be copied without recording what they actually proved.
  - Mitigation: capture command plus failure it caught.

### Failure modes

- The task may turn into a command dump with no evidence mapping.
- It says not to broaden beyond evidence gathered, but does not require provenance for each recurring check.
- No verification requires that the recurring note be used by the next Step 3 batch.

### Hardening actions

- Require the recurring note to include, for each check:
  - command
  - caller category
  - why it exists
  - which failure it caught in this batch
- Require the next Step 3 batch template to reference the recurring note explicitly.

## Specific failure-mode answers

### Are file references correct?

- Yes for the referenced planning docs.
- Missing concrete references for:
  - migration paths
  - startup entry points
  - blocker artifact location
  - recurring-gate artifact location

### Are model/class names correct against actual source?

- The step itself does not name many models/classes, which avoids direct mismatch risk.
- Where it implies startup and migration wiring, the real active files are:
  - [src/orchestrator/api/app.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/api/app.py)
  - [src/orchestrator/cli/main.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/cli/main.py)
  - [src/orchestrator/db/migrations/env.py](/Users/peter/code/task-world/worktrees/r51/src/orchestrator/db/migrations/env.py)
  - [scripts/serve.py](/Users/peter/code/task-world/worktrees/r51/scripts/serve.py)
  - [scripts/worker.py](/Users/peter/code/task-world/worktrees/r51/scripts/worker.py)

### Does "create" vs "update" match file existence?

- The step says "write or update" and "add or update", but it does not specify target files. That is ambiguous and should be tightened.

### Are format-dependent interfaces specified explicitly?

- No. Checklist format, blocker format, and recurring-gate note format are all underspecified.

### Will existing tests break?

- They can, because there are current external callers importing internal paths.
- The larger risk is the inverse: tests may stay green because the sweep does not require enough caller-specific verification.

### Are async/infrastructure dependencies resolved?

- Partially. The step uses `uv run`, which matches repo rules.
- It does not account for infrastructure-sensitive commands:
  - worker script needs `ORCHESTRATOR_DB`
  - Alembic checks need the configured migration path
  - some startup imports may have side effects tied to environment or cwd

### Persistence layer complete?

- Not applicable for this step. It does not introduce new persisted fields or repositories.
- Migration callers still matter as consumers and must be checked if `db` or `runners.profiles.models` boundaries move.

### Integration test assertions specified?

- Not well enough. The step names pytest targets but not the assertions or suites that prove changed startup/import behavior.

### Component wiring verified?

- Weakly.
- No new handler/adapter is created here, but Step 4 must verify replacement of old call sites after Step 3. The current wording does not explicitly require proving that active entry points now import through top-level module interfaces.

## Minimum hardening needed before execution

1. Require Step 3 output to name the exact obsolete and canonical import prefixes for the completed batch.
2. Restrict Task 1 searches to non-source callers plus named startup entry points; do not sweep all of `src/orchestrator`.
3. Search both `from ... import ...` and `import ...` forms.
4. Define a fixed checklist format and a fixed blocker format.
5. Name the concrete startup and migration files that must be checked in this repo.
6. Replace generic import-smoke examples with caller-specific commands that exercise the active path.
7. Require each migrated batch to prove the old call site was replaced, not just that a new import path exists.

## Overall assessment

The step is directionally correct and matches the tranche intent, but it is not execution-hard yet. The main weaknesses are scope control, false-positive-heavy search commands, vague artifact locations, and weak verification of active startup call sites. Tightening those four areas would materially reduce the risk of a "green but not actually migrated" Step 4 run.
