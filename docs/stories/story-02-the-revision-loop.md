# Story 02: The Revision Loop

*The agent builds something, the verifier isn't happy, auto-verify catches a real problem, and the agent gets another shot. Then another.*

---

Maya kicks off a run using the `add-auth-middleware` routine against `acme-backend`. This one's more demanding than the widgets endpoint -- the routine has auto-verify commands configured:

```yaml
auto_verify:
  - command: "uv run pytest tests/ -x"
    label: "Tests pass"
    must_pass: true
  - command: "uv run pyright"
    label: "Type check"
    must_pass: false
```

Tests are must-pass. Type checking is advisory. The run starts, the agent gets to work.

### Attempt 1: The Tests Don't Lie

The agent builds the middleware, marks its checklist items DONE, and submits. The checklist gate passes -- all CRITICAL items are marked. But before the verifier prompt fires, auto-verify runs.

```
[14:12:01] Task build-auth: status → VERIFYING
[14:12:02] Auto-verify: running "uv run pytest tests/ -x"
[14:12:18] Auto-verify: FAILED (exit code 1)
           tests/test_auth.py::test_token_validation FAILED
           AssertionError: expected 401, got 500
[14:12:18] Auto-verify: "Tests pass" is must_pass — sending back to builder
[14:12:18] Task build-auth: status → BUILDING (attempt 2 of 3)
```

The must-pass auto-verify item failed. The task goes back to BUILDING without ever reaching the grading phase. The agent gets a fresh builder prompt -- no memory of attempt 1, but the prompt now includes feedback:

```
Previous attempt feedback:
- Auto-verify "Tests pass" FAILED: tests/test_auth.py::test_token_validation
  FAILED — AssertionError: expected 401, got 500
```

The agent sees the test output, understands the bug (it was raising a generic 500 instead of returning 401 for invalid tokens), and fixes it.

### Attempt 2: The Verifier Has Notes

This time auto-verify passes. Both `pytest` and `pyright` succeed. The task stays in VERIFYING and the agent gets its verifier prompt.

The verifier -- remember, fresh context, no memory of building or the first attempt -- reviews the code and grades each requirement:

```
[14:15:03] Grade R1 (Middleware registered): PASS
[14:15:08] Grade R2 (Token validation): PASS
[14:15:15] Grade R3 (Error responses follow API convention): NEEDS_REVISION
           "Returns plain text error messages instead of the standard
            JSON error envelope used by other endpoints"
[14:15:20] Grade R4 (Tests cover happy + error paths): PASS
```

The grade threshold for this routine is set to require an average above NEEDS_REVISION (grades are numeric internally: PASS=4, NEEDS_REVISION=2, MAJOR_ISSUES=1, FAIL=0). With three PASS (12) and one NEEDS_REVISION (2), the average is 3.5. The threshold is 3.0. Numerically, it passes.

But wait -- the routine also has a per-item minimum: no CRITICAL item can be below PASS. R3 is CRITICAL and got NEEDS_REVISION.

```
[14:15:21] Grade threshold: average 3.5 >= 3.0 ✓
[14:15:21] Per-item check: R3 (CRITICAL) grade NEEDS_REVISION < PASS ✗
[14:15:21] Task build-auth: status → BUILDING (attempt 3 of 3)
```

Back to building. Attempt 3. The agent gets another fresh prompt, this time with the verifier's feedback about the error response format. It reads the existing error handlers, sees the JSON envelope pattern, and updates the middleware to match.

### Attempt 3: Third Time

Auto-verify passes. The verifier grades everything PASS. The grade threshold clears. The per-item check clears.

```
[14:18:44] Task build-auth: status → COMPLETED
```

Three attempts, two pieces of real feedback, one working feature. The attempt history is preserved -- Maya can later see that attempt 1 failed on tests, attempt 2 failed on code review, and attempt 3 passed. Each attempt records its token usage, duration, and the git commit range it produced.

```
GET /api/runs/{id}/tasks/build-auth
→ 200 {
    "attempts": [
      { "attempt_num": 1, "status": "revision", "tokens": 12400, "duration_s": 17 },
      { "attempt_num": 2, "status": "revision", "tokens": 15200, "duration_s": 20 },
      { "attempt_num": 3, "status": "passed",   "tokens": 14800, "duration_s": 18 }
    ],
    "total_tokens": 42400,
    ...
  }
```

42,400 tokens for a middleware. Not cheap, but the alternative was Maya writing it herself, and she had three other things to do today.

Had the agent failed attempt 3, the task would have moved to FAILED (max_attempts reached), and the run with it. Maya would have had to decide whether to tweak the routine and try again or just write the code herself. But today, three was enough.

---

*This story covers: auto-verify (must-pass and advisory), revision loop, fresh context per attempt, verifier grading, grade threshold (average and per-item), attempt tracking, max attempts, token/cost tracking.*
