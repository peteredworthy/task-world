# Test Strategy Improvements

Generated from analysis of known state/UI bugs. Six planned improvements plus gaps none of them address.

## Known Bugs That Motivated This

| # | Bug | Location | Root cause |
|---|-----|----------|------------|
| 1 | `approval_requested` WS event not handled → pending-actions never updates from WS | `useWebSocket.ts:95` | Missing case in switch |
| 2 | `pending_user_action` missing from `TaskStatus` frontend type → silent render failure | `types/enums.ts:3` | Hand-maintained type drift |
| 3 | `TERMINAL_STATUSES` has `cancelled` (nonexistent), missing `stopping` → polling loops forever | `useApi.ts:5` | Hand-maintained type drift |
| 4 | `autoOpenedRef` never resets → only first pending action ever auto-opens | `RunDetail.tsx:168` | Logic bug in useEffect |
| 5 | WS batch timer race: buffer cleared inside lock, broadcast outside → second flush interleaves | `websocket.py:164` | asyncio concurrency race |
| 6 | `transition_to_recovering` and `transition_force_accept` have zero test coverage | `transitions.py` | Coverage blind spot |
| 7 | `isRunStuck()` untested → stuck-run warning never verified; active run with max-attempt failed task may show no signal | `RunDetail.tsx` | No test for this render path |
| 8 | Under high event load (fan-out, many transitions), `run_status_changed` from second batch can arrive before `task_status_changed` from first → transient incoherent display (active badge on completed run) | `websocket.py:164` | Same race as bug 5, different symptom |

---

## Planned Improvements

### Priority 1 — Enum Codegen (3h, fixes bugs 2 & 3)

**What:** Add `scripts/export_enums.py` that reads `src/orchestrator/config/enums.py` via AST/introspection and emits `ui/src/types/generated-enums.ts`. CI runs the script and asserts `git diff --exit-code` is clean.

**Remove** hand-maintained `TaskStatus`, `RunStatus`, `PauseReason` from `types/enums.ts` and import from generated file.

**Why it catches bugs 2 & 3:** `pending_user_action` is in the Python enum but not in the TypeScript type. `cancelled` is in the TypeScript type but not in the Python enum. Codegen makes these a CI failure instead of a runtime mystery.

**Fast iteration value:** LLM agent adding a backend status gets an immediate TypeScript error. No manual cross-reference needed.

---

### Priority 2 — Coverage Thresholds (30min, exposes bug 6)

**What:** Add to `pyproject.toml` `[tool.pytest.ini_options]`:
```
addopts = "-n auto --dist loadfile --timeout=30 --cov=src/orchestrator --cov-branch --cov-report=term-missing --cov-fail-under=80"
```

Add to `ui/vitest.config.ts`:
```ts
coverage: {
  provider: 'v8',
  thresholds: { lines: 70, branches: 65 }
}
```

**Why it catches bug 6:** `pytest-cov` is already installed but never invoked. `transition_to_recovering` and `transition_force_accept` have zero coverage. Thresholds block merges that ship untested transitions.

**Fast iteration value:** Agent adding a new transition function fails CI immediately if no test is written.

---

### Priority 3 — WS `processEvent` Unit Tests (1d, fixes bug 1)

**What:** Add `tests/unit/test_ws_process_event.ts` using `vitest-websocket-mock`. For every event type the backend can emit, assert:
1. The correct `queryClient.invalidateQueries` calls fire
2. No extra invalidations (performance regression guard)

Critical cases: `approval_requested`, `clarification_requested`, `run_status_changed`, `task_status_changed`, `checklist_gate_evaluated`.

```ts
it('approval_requested invalidates pending-actions', async () => {
  const server = new WS('ws://localhost/api/ws/runs/r1');
  const { result } = renderHook(() => useWebSocket('r1', qc));
  server.send(JSON.stringify({ type: 'approval_requested', run_id: 'r1' }));
  expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['pending-actions', 'r1'] });
});
```

**Why it catches bug 1:** The current test suite never fires a WS message at `useWebSocket`. This test fails immediately on the missing `approval_requested` case.

---

### Priority 4 — Playwright State Transition Smoke Tests (2d, catches bug 4)

**What:** Extend `tests/e2e/visual-regression.spec.ts` with ~10 state-transition scenarios. Use `page.route()` + `page.evaluate()` to inject WS frames. Test:

- All `pause_reason` variants render correct banners
- `stopping` state shows the right badge (no resume/pause buttons)
- `approval_requested` WS event causes pending-actions badge to update within 2s
- `isRunStuck()` scenario (active run, task failed at max attempts) shows stuck warning
- `autoOpenedRef` bug: a second pending action after modal dismiss auto-opens

```ts
test('approval_requested WS event updates badge without reload', async ({ page }) => {
  await page.goto('/runs/test-run-id');
  await injectWebSocketFrame(page, { type: 'approval_requested', run_id: 'test-run-id' });
  await expect(page.getByTestId('pending-actions-badge')).toBeVisible({ timeout: 2000 });
});
```

**Why it catches bug 4:** The `autoOpenedRef` bug is only observable in a live browser environment after a modal is dismissed — unit tests can't catch it.

---

### Priority 5 — API Contract Testing via schemathesis (1w)

**What:** FastAPI auto-generates an OpenAPI schema at `/openapi.json`. Run `schemathesis run http://localhost:8000/openapi.json --checks all` as a CI step against the test app. This generates requests from the schema spec and verifies response shapes match.

Add a `make check-schema` target that:
1. Starts the test app with a temp DB
2. Runs schemathesis for 60 seconds (stateful mode to chain requests)
3. Fails on any 5xx, schema validation error, or unhandled exception

**What it catches:** API endpoints that accept invalid input without error, responses that don't match declared schemas, missing error cases. Finds the "premature submission" guard (verification with ungraded CRITICAL items) and force-accept edge cases automatically.

**Tradeoffs:** 60-90s added to CI. Flaky if the test app leaks state between workers. Use `--validate-schema=false` initially to skip known schema drift until codegen (Priority 1) is done.

---

### Priority 6 — Property-Based State Machine Tests (1w)

**What:** Use `hypothesis` (Python) to generate arbitrary valid transition sequences from `VALID_TRANSITIONS` and verify invariants:

- A `COMPLETED` task never transitions out
- `max_attempts` is always respected
- `check_run_completion` returns consistent `RunStatus` for any task set
- `transition_force_accept` from `FAILED` always produces `COMPLETED` regardless of attempt count

```python
from hypothesis import given, strategies as st

@given(st.lists(st.sampled_from(list(VALID_TRANSITIONS.keys())), min_size=1, max_size=20))
def test_no_invalid_terminal_escape(transition_sequence):
    state = build_task_from_sequence(transition_sequence)
    if state.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        assert len(VALID_TRANSITIONS[state.status]) == 0
```

Use `fast-check` (TypeScript) to generate random WebSocket event sequences and assert the UI never reaches an incoherent display state.

**What it catches:** Unknown sequences no human would think to test. Especially valuable for `check_step_progression` with `repeat_for` expansion and backward transition loops.

---

## Gaps None of the Above Address

### Gap A — Async Concurrency Races (Bug 5 class)

**Bug 5** is a race between `_flush_after_window` releasing the lock and calling `broadcast_to_run` outside it. Engineering a deterministic failure case is fragile and non-reproducible. The more practical fix is **pattern enforcement**: make the race structurally impossible, then verify the structure hasn't drifted.

**Preferred approach: AST-based linter rule**

The invariants are small and stable:
- `async with self._buffer_lock` must not be followed by `await` outside the lock scope on any path that also mutates `_event_buffers` or `_timer_tasks`
- Timer cleanup (`del self._timer_tasks[run_id]`) and buffer clear (`self._event_buffers[run_id] = []`) must happen in the same lock acquisition
- `broadcast_to_run` (the network call) must not be called while holding `_buffer_lock`

Write an AST visitor (`scripts/check_async_patterns.py`) that walks `src/orchestrator/api/websocket.py` and any file importing `_buffer_lock` and asserts these invariants. Run as a pre-commit hook. Runs in milliseconds, zero flakiness, catches deviations before they reach CI.

```python
# scripts/check_async_patterns.py — sketch
import ast, sys

GUARDED_ATTRS = {'_event_buffers', '_timer_tasks'}
BROADCAST_CALLS = {'broadcast_to_run'}

class LockPatternChecker(ast.NodeVisitor):
    """Verify broadcast_to_run is never called inside _buffer_lock context."""
    def visit_AsyncWith(self, node):
        lock_names = {
            kw.value.attr
            for item in node.items
            if isinstance(item.context_expr, ast.Attribute)
            for kw in [item]
        }
        if '_buffer_lock' in str(ast.dump(node)):
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
            for call in calls:
                if isinstance(call.func, ast.Attribute) and call.func.attr in BROADCAST_CALLS:
                    print(f"ERROR line {call.lineno}: {call.func.attr} inside _buffer_lock")
                    sys.exit(1)
        self.generic_visit(node)
```

**Also applies to:** Any asyncio code with shared mutable state — `executor.py` heartbeat, `app.py` startup recovery. Add those files to the checker's scope as they grow.

---

### Gap B — WS Reconnection Event Gap

**Problem:** When the frontend WS disconnects, reconnect uses exponential backoff: 1s → 2s → 4s → ... → 30s, max 10 attempts. State changes during this window are only caught by the 10-second polling fallback. The UI can show a run as `active` when it has actually `completed` or `failed`. No test covers this.

**Approach: unit-level, not Playwright.** A Playwright test that waits up to 12s for polling to fire is too slow and fragile for routine CI. The same coverage is achievable with a fast unit test:

```ts
it('polls on WS disconnect and updates run status', async () => {
  vi.useFakeTimers();
  const server = new WS('ws://localhost/api/ws/runs/r1');

  // Render with active run
  const { result } = renderHook(() => useWebSocket('r1', qc));
  
  // Simulate disconnect
  server.close();
  
  // Advance past polling interval (10s)
  await vi.advanceTimersByTimeAsync(11_000);
  
  // Assert polling query fired
  expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
  
  vi.useRealTimers();
});
```

Use `vitest-websocket-mock` for the WS server and `vi.useFakeTimers()` to control the polling interval — no real sleeps, runs in milliseconds.

Also: Add a backend integration test that verifies the activity feed endpoint returns all events since a given cursor, so a reconnecting client can catch up without a full reload.

---

### Gap C — Mutation Testing with LLM Significance Scoring

**Problem:** Tests can pass while assertions are meaningless. `assert response.status_code == 200` passes whether the response body is correct or garbage. Traditional mutation testing surfaces this but produces too much noise: many surviving mutations are semantically equivalent to the original and not worth fixing. The signal-to-noise ratio makes results hard to act on.

**The missing piece:** The value isn't just "did the tests catch this mutation" — it's "was this mutation *worth* catching?" Previously, judging significance required manual review. LLMs can now do this at scale: given `(original_code, mutated_code, test_output_before, test_output_after)`, classify the mutation as `equivalent / trivial / significant / critical`.

**Approach: scoped pipeline with LLM judge**

Run `mutmut` (Python) / `stryker` (TypeScript) in incremental mode against only the files changed in a PR. Use `stryker`'s `--since` flag or `mutmut`'s `--paths-to-mutate` filtered to `git diff --name-only`. This scopes the mutation count to hundreds, not thousands.

Feed surviving mutations to a Claude API call:

```python
# scripts/judge_mutations.py — sketch
def judge_mutation(original: str, mutant: str, test_diff: str) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system="You are a mutation testing judge. Classify surviving mutations.",
        messages=[{
            "role": "user",
            "content": f"""
Original code:
{original}

Mutant (what changed):
{mutant}

Test output delta (tests that now pass/fail differently):
{test_diff}

Classify this mutation:
- equivalent: semantically identical to original, impossible to distinguish
- trivial: detectable difference but not a realistic bug (e.g. off-by-one in a log message)
- significant: represents a real logic error that tests should catch
- critical: represents a dangerous failure mode (data loss, wrong state transition, security)

Reply with JSON: {{"classification": "...", "reason": "one sentence"}}
"""
        }]
    )
    return json.loads(response.content[0].text)
```

**Output:** A report of surviving mutations classified by severity. Only `significant` and `critical` survivors require action.

**Cost design — required, not optional:** Naive usage is expensive. A single file with 200 mutations × ~800 tokens per judge call = ~160K tokens per run. At current pricing that's acceptable for a weekly job but not per-PR. Design constraints:

1. **Scope to diff only** — never mutate files untouched by the PR. Use `mutmut run --paths-to-mutate=$(git diff --name-only origin/main)`.
2. **Filter before judging** — only send *surviving* mutations (tests didn't catch them) to the LLM. Killed mutations need no judgement.
3. **Cache by content hash** — `(original_code_hash, mutant_hash)` → classification is stable across runs. A mutation judged `equivalent` once never needs re-judging.
4. **Batch API calls** — use the Anthropic Batch API for the judge step. Async, ~50% cheaper, no latency pressure for a weekly job.
5. **Cap per run** — set a hard limit (e.g. 50 LLM calls per run). If surviving mutations exceed cap, prioritize by file criticality (`transitions.py` > everything else).

**CI integration:** Weekly job, not per-PR. Report `significant` + `critical` survivors as GitHub annotations on the relevant lines. A count above threshold (e.g. >5 critical survivors) blocks the next release.

**Note on the inverse:** A mutation that *killed* tests but the LLM rates as `equivalent` is a sign your tests are asserting on the wrong thing — overfitted to implementation, not behaviour. These are worth reviewing too.

---

### Priority 7 — Integration Test Factoring Audit (0.5d)

**What:** A scan of existing tests for the anti-pattern of running pure logic through an expensive integration harness when a unit test would cover it faster and more directly. The rule: if the same logical variation (different enum value, different string input) is being tested at both the unit and integration layer, the integration layer should be collapsed to a single wiring smoke test.

Two concrete cases found in this codebase:

---

#### Case A — `test_api_runs_validation.py` duplicates unit validators across HTTP

`tests/unit/test_api_runs_validation.py` already tests every `agent_type`, `merge_strategy`, and `agent_config` validator case directly against the Pydantic schema — no HTTP, no DB, runs in milliseconds.

`tests/integration/test_api_runs_validation.py` then repeats those same cases via full HTTP requests against an in-memory app. Of its ~20 tests, roughly 15 are pure validator variations (valid/invalid/normalised) that are already covered at the unit layer. Each one spins up ASGITransport, a DB engine, and makes a round-trip HTTP call just to confirm the validator rejects the same input the unit test already confirmed it rejects.

**What to keep at integration level:** Two tests — one that confirms an invalid `agent_type` returns 422 (verifies the validator is wired to the endpoint) and one that confirms a valid request returns 201 (end-to-end smoke). Everything else belongs only at the unit layer.

**What to keep at unit level:** All the current `test_api_runs_validation.py` unit tests, unchanged. They're correctly testing the validators.

**Effort:** 30 minutes to delete the duplicate integration cases.

**Residual risk of not doing this:** Validator logic changes get tested via HTTP twice, so a developer adding a new valid `merge_strategy` value needs to add two test cases in two files. Duplication creates a false signal: a large test count that doesn't represent proportionally more coverage.

---

#### Case B — `StatusBadge.test.tsx` renders components to check React renders children

`ui/tests/components/StatusBadge.test.tsx` renders `RunStatusBadge` and `TaskStatusBadge` through jsdom + React and asserts `screen.getByText(status)`. The assertion confirms that React renders `{status}` as a text node. This is a React guarantee, not component logic.

The actual logic in these components — `runStatusColor(status)` and `taskStatusColor(status)` — is already unit-tested in `ui/tests/lib/status.test.ts`. But the component tests don't assert the CSS class at all, so they neither catch color regressions nor duplicate `status.test.ts`'s coverage in a meaningful way. They run 11 jsdom renders to assert that string interpolation works.

**What to keep:** One snapshot test per component that renders a single representative status and captures the full element (including `className`). This confirms the component renders without crashing AND that the class lookup is wired up, in a single render.

**What to delete:** The eleven `it.each` cases that only check `getByText(status)`.

**Why this matters:** The current tests miss the only real failure mode — `runStatusColor` returning the wrong class for a status. If `stopping` were accidentally mapped to `bg-status-failed` instead of `bg-status-paused`, every StatusBadge test would still pass.

---

**General rule these cases illustrate:**

> If the same logical variation (different input value, different enum case) is tested at both the unit layer and the integration layer, the integration tests are paying an integration tax (DB setup, HTTP stack, jsdom render) for coverage that already exists one layer down. Integration tests should verify *wiring* — that components or endpoints are connected to the logic — not repeat the logic's own test matrix.

**Applying this rule going forward:** When adding integration tests for a feature with pure-function logic, write the logic variations as unit tests first. One integration test that calls the endpoint/renders the component with one representative input is then sufficient to confirm the wiring. If the integration test is parametrised over more than 2-3 variations of the same input type, that's a signal the variations should move to the unit layer.

---

## Summary Table

| Item | Effort | Bugs caught | Currently missed |
|------|--------|-------------|------------------|
| Enum codegen | 3h | 2, 3 | — |
| Coverage thresholds | 30min | 6 (surfaces) | — |
| WS processEvent tests | 1d | 1 | — |
| Playwright state transitions | 2d | 4 | — |
| schemathesis contract tests | 1w | schema drift | — |
| Property-based SM tests | 1w | unknown sequences | — |
| **Async pattern linter** | **1d** | **5 (prevents recurrence)** | **all 6 above miss this** |
| **WS reconnection unit tests** | **0.5d** | **stale-UI-on-disconnect** | **all 6 above miss this** |
| **Mutation + LLM judge** | **2d setup + ongoing** | **weak assertions** | **all 6 above miss this; cost design required** |
| **Integration test factoring** | **0.5d** | **false coverage signal, slow CI** | **structural: prevents the duplication growing** |
