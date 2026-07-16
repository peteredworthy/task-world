# W5.5 Task 2 Report

## Status

Implemented atomic check-output externalization on `codex/w5-artifact-output`.
The durable Task 2 queue checkbox remains unchecked for controller review; all
Task 2 plan step checkboxes are checked.

## Files changed

- Canonical contracts and readers: `src/orchestrator/graph/models.py`,
  `src/orchestrator/graph/projections.py`,
  `src/orchestrator/api/routers/runs.py`.
- Producer and composition: `src/orchestrator/graph_runtime/dispatch.py`,
  `src/orchestrator/graph_runtime/__init__.py`,
  `src/orchestrator/workflow/graph_driver.py`.
- New producer/failure integration coverage:
  `tests/integration/test_check_output_artifacts.py`.
- Existing model, projection, dispatch, driver, callback, fixture, and E2E tests
  were migrated to canonical `stdout_tail`/`stderr_tail` fields and explicit
  artifact-store injection.
- Tracking: `docs/superpowers/plans/2026-07-15-w5-artifact-output.md` and
  `docs/dynamic-graph/w5-progress-ledger.md`.

## RED evidence

Command:

```text
uv run pytest tests/unit/test_graph_models.py -k check_output_artifact tests/integration/test_check_output_artifacts.py -q
```

Exact result: `1 failed, 1 error in 2.70s`.

- The model test failed with six validation errors: existing `stdout` and
  `stderr` were required, while `stdout_tail`, `stdout_ref`, `stderr_tail`, and
  `stderr_ref` were forbidden extras.
- Integration collection errored with
  `ImportError: cannot import name 'CHECK_OUTPUT_TAIL_CHARS' from 'orchestrator.graph_runtime'`.
- This was the expected missing canonical fields, externalization API, and
  artifact-store dispatch integration—not a test typo or setup failure.

## GREEN evidence

- Required focused command:
  `249 passed in 19.23s`.
- Full suite:
  `4792 passed, 3 skipped, 3 warnings in 102.45s`; warnings are the existing
  Python 3.12 aiosqlite datetime-adapter deprecations.
- `uv run ruff check .`: `All checks passed!`
- `uv run pyright`: `0 errors, 0 warnings, 0 informations` plus the tool's
  available-version notice.
- `uv run ruff format --check .`: `708 files already formatted`.
- `git diff --check`: exit 0 with no output.
- Commit hooks on the implementation commit passed Ruff, Ruff format, secret
  detection, Pyright, pytest, module imports, signal routing, UI lint, and UI
  typecheck; enum drift had no applicable files.

## Ordering and failure evidence

- Sub-threshold stdout/stderr remain complete in tails and create no artifact
  root or reference.
- Over-threshold tests execute real shell checks producing 17,000 bytes on each
  stream. The real temporary `FilesystemArtifactStore` reads back every byte,
  while durable callback events expose 4,000-character tails and typed refs.
- A real filesystem failure (store root occupied by a file) occurs before the
  callback and leaves no accepted callback/check-result event.
- An integration store writes through to the real filesystem CAS and then uses
  a real SQLite trigger to reject event insertion. The callback append fails,
  but the resulting orphan remains readable and integrity checked.
- Externalization runs before `_submit_check_result`; stdout is written before
  stderr, and any failed write prevents event append. Append failures do not
  remove already durable blobs.

## Self-review

- Confirmed canonical `CheckResultValue` removes `stdout` and `stderr`, forbids
  them as extras, and enforces `*_truncated == (*_ref is not None)`.
- Confirmed byte threshold is exactly 16,384 UTF-8 bytes and tails are exactly
  the final 4,000 Unicode characters.
- Confirmed reducers, projections, blockers, activity summaries, command
  handlers, and prompt paths receive no store and perform no hydration.
- Confirmed production `GraphRunDriver` resolves the main git worktree and
  injects a side-effect-free store rooted at its `.orchestrator/artifacts`, not
  at the run worktree.
- Searched graph and graph-runtime production code for old quoted `stdout` and
  `stderr` canonical keys; none remain.
- Reviewed the complete diff and found no compatibility aliases or unrelated
  behavior additions.

## Commits

- `0c8b26a1b` — `Externalize large check output artifacts`
- Ledger/report tracking commit: recorded after creation; see final response.

## Concerns

None. Task 3 remains responsible for explicit bounded hydration and artifact
read APIs; Task 2 intentionally leaves reducers and ordinary prompts tail-only.

## Boundary Coverage Review Fix

- Added real producer-path regressions proving exactly 16,384 UTF-8 bytes stay
  inline without creating a blob/reference, while 16,385 bytes produce a typed
  reference whose real temporary filesystem blob contains the complete output.
- Added a 16,385-byte multibyte case (`16,381` ASCII characters plus one
  four-byte emoji) proving thresholding uses UTF-8 bytes while the retained tail
  is the final 4,000 Unicode characters (`3,999` ASCII characters plus the
  emoji), not the final 4,000 bytes.
- `uv run pytest tests/integration/test_check_output_artifacts.py -q`
  - Result: `7 passed in 4.68s`.
- `uv run pytest tests/integration/test_check_output_artifacts.py tests/unit/test_graph_models.py -k 'check_output_artifact or test_exact_byte_threshold or test_one_byte_above_threshold or test_multibyte_output' -q`
  - Result: `8 passed in 4.82s`.
- `uv run ruff check tests/integration/test_check_output_artifacts.py tests/unit/test_graph_models.py`
  - Result: `All checks passed!`.
- `uv run pyright tests/integration/test_check_output_artifacts.py tests/unit/test_graph_models.py`
  - Result: `0 errors, 0 warnings, 0 informations` (plus the available-version notice).
- `uv run ruff format --check tests/integration/test_check_output_artifacts.py tests/unit/test_graph_models.py`
  - Result: `2 files already formatted`.
- `git diff --check`
  - Result: passed with no output.
- Review-fix commit: `ae3b35f60` (`Cover check output artifact boundaries`).
