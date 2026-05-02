# Phase 4 Evidence Bundle Schema

Every oversight-loop slice should write one JSON evidence bundle using
`schema_version: phase4.evidence.v1`.

Required planner-facing fields:

- `assumption_tested`: the assumption this slice was designed to test.
- `summary`: concise result of the slice.
- `commands_run`: commands and exit codes used as evidence.
- `test_results`: pass/fail/skip/not-run records.
- `target_bug_reproduced`: `reproduced`, `not_reproduced`, `not_targeted`, or `unknown`.
- `real_frontend_path_exercised`: whether the real user-facing path ran.
- `real_execution_surface`: the actual surface checked, not a helper-only proxy.
- `files_changed`: changed files relevant to the slice.
- `evidence_files`: artifacts a reviewer or next planner can inspect.
- `open_uncertainties`: remaining unknowns.
- `next_recommendation`: `proceed`, `replan`, `stop`, or `environment_blocked`.
- `outcome`: `verified_fix`, `bug_not_reproduced`, `behavior_already_correct`,
  `environment_blocked`, `needs_revision`, `partial_progress`, or
  `unrelated_failure`.

The next planner should consume this bundle directly before authoring the next
slice. `verified_fix`, `bug_not_reproduced`, `behavior_already_correct`,
`environment_blocked`, `needs_revision`, `partial_progress`, and
`unrelated_failure` are distinct outcomes and must not be collapsed into a
generic pass/fail summary.
