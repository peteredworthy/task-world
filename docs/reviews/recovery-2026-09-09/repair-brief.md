# First server repair: reviewable scope

The user authorized implementation, required checks, and restart when idle on
September 9: “you have my permission, keep going”. Work is isolated on
`codex/recovery-stabilization` in `worktrees/recovery-stabilization`.

Priority 1 is responsiveness during normal submission. The existing
`WorkflowService._run_event_sourced_worktree_commit` persists a request and then
calls `commit_uncommitted_changes_or_raise` synchronously. The latter invokes
`subprocess.run` for Git; hooks take minutes. In the live baseline, health/read
requests timed out during 6m29s of commit checks and resumed after they finished.

Keep the durable request/completion/failure order, hooks, error propagation,
and accurate commit SHA. Offload only blocking Git work. Preserve one mutation
owner per checkout across overlapping requests, resets, retries and cancellation.
Do not pass an AsyncSession to a worker thread. Cancellation must not release
ownership while a Git child continues writing. Respect the signal-queue and
injection boundaries; do not add a shared API/executor global lock. The existing
graph executor's shield-and-drain pattern is useful reference code, not proof
that the legacy submission path already has safe concurrency.

Regression starting points:

- `tests/unit/test_worktree_commit_events.py`
- `tests/unit/test_worktree_reset_events.py`
- `tests/unit/test_git_autocommit_hook_retry.py`
- `tests/integration/test_check_and_apply_methods.py`

Add real temporary Git hooks that wait on an explicit test release mechanism.
While a hook is waiting, a real integration health/read request must return
within a short bounded timeout. Test duplicate submit, reset and cancellation
without racing writes or losing the durable receipt. Release the hook and
verify the exact committed files and events. Do not bypass pre-commit.

Priority 2 is invalid graph checks accepted before work. The exact reproduction
is in `failed-node.json`: `dynamic_feature_hidden_oracle` is bound while the
run snapshot's hidden command is empty. The required final acceptance command
exists separately. Graph position 486 records the missing executable command.

Reject the unavailable binding through semantic construction and other accepted
authoring paths before expensive work, with a typed actionable reason. Use one
canonical binding resolver/validator for acceptance and dispatch. Do not silently
reinterpret hidden checks as final acceptance or remove required checks. Keep
valid concrete commands and configured bindings working after persistence and
replay. Capture an actionable root cause when dispatch still encounters an
infrastructure/configuration failure. Do not turn a non-retryable configuration
error into an LLM retry loop.

Run relevant focused tests during edits, then required checks before activation.
Server activation requires a tested revision and an idle-run check. A successful
repair is a live responsive submission and a new dynamic run reaching independent
final acceptance without manual graph repair, not only passing unit tests.

The live Unicode correction added one bounded requirement: fresh verifiers
must receive the actual task contract, configured commands, and trustworthy
current-attempt check evidence. Both original and supplemental acceptance
commands passed, but the recorded verifier prompt omitted them and the task
instructions. The verifier substituted a separate `make test` invocation,
reported failures, and failed the run. Correct prompt construction and executor
wiring without sharing builder history, treating old receipts as current, or
instructing verifiers to ignore real failures. Keep the new behavior narrowly
tied to this incident.
