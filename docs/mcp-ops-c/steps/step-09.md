# Step 9: Final Validation

Perform final validation to ensure the entire implementation is correct, all tests pass, code quality checks are clean, and no regressions were introduced. This is the last gate before the feature is considered complete.

## Intent Verification
**Original Intent**: All existing tests continue to pass (no regressions); `uv run pre-commit run --all-files` passes cleanly (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullets 15-16).
**Functionality to Produce**:
- Full test suite passes (unit + integration)
- Pre-commit checks pass (linting, formatting, type checking)
- No regressions in existing functionality
- All implementation steps verified complete

**Final Verification Criteria**:
- `uv run pytest` exits with code 0
- `uv run pre-commit run --all-files` exits with code 0
- Test counts equal or exceed baseline (330 unit, 235 integration, 221 frontend)

---

## Task 1: Run Full Test Suite
**Description**:
Execute the complete test suite to confirm all tests pass, including new tests from Steps 1-8 and all existing tests.

**Implementation Plan (Do These Steps)**
- [ ] Run all backend tests:
```bash
uv run pytest tests/ -v --timeout=60
```
- [ ] Confirm test count meets or exceeds baseline:
  - Unit tests: ≥ 330 (baseline from MEMORY.md)
  - Integration tests: ≥ 235
- [ ] If any tests fail, investigate and fix the root cause
- [ ] Run frontend tests if UI changes were made:
```bash
cd ui && npm run test -- --run
```

**References**
- Test baseline: 330 unit tests, 235 integration tests, 221 frontend tests (from MEMORY.md)
- Plan: `docs/mcp-ops-c/plan.md` — Step 9: Final validation

**Functionality (Expected Outcomes)**
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No new test failures compared to baseline
- [ ] New tests from Steps 1-8 are included in the count

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/ -v --timeout=60` exits with code 0
- [ ] Test count output shows increased numbers (new tests added)

---

## Task 2: Run Pre-Commit Checks
**Description**:
Run all pre-commit hooks to verify code quality, formatting, linting, and type checking.

**Implementation Plan (Do These Steps)**
- [ ] Run pre-commit checks:
```bash
uv run pre-commit run --all-files
```
- [ ] Fix any failures:
  - Formatting issues → `uv run ruff format .`
  - Linting issues → `uv run ruff check --fix .`
  - Type issues → fix type annotations
- [ ] Re-run until clean

**Constraints**
- All checks must pass before marking this task complete
- Do not disable or skip any pre-commit hooks

**Functionality (Expected Outcomes)**
- [ ] `uv run pre-commit run --all-files` exits with code 0
- [ ] No formatting, linting, or type errors

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pre-commit run --all-files` exits with code 0

---

## Task 3: Final Review and Verification
**Description**:
Perform a final review of all changes to ensure completeness, quality, and security compliance.

**Implementation Plan (Do These Steps)**
- [ ] Review git diff of all changed files:
```bash
git diff main --stat
git diff main --name-only
```
- [ ] Verify no TODO/FIXME items left in new code:
```bash
grep -rn "TODO\|FIXME" src/orchestrator/ --include="*.py" | grep -v "__pycache__"
```
- [ ] Verify auth tokens never appear in YAML, prompts, or logs:
  - Check `MCPServerConfig.auth_token_env` usage across all agent implementations
  - Confirm resolved token values are not logged
- [ ] Verify backward compatibility: existing routines without new fields still work
- [ ] Cross-check with `docs/mcp-ops-c/intent.md` "Definition of Complete" — all items addressed

**References**
- Intent: `docs/mcp-ops-c/intent.md` — Definition of Complete (16 items)
- Architecture: `docs/mcp-ops-c/architecture.md` — Security Considerations
- Plan: `docs/mcp-ops-c/plan.md` — Key Decisions table

**Functionality (Expected Outcomes)**
- [ ] No unresolved TODOs in new code
- [ ] Auth tokens handled securely across all agents
- [ ] All Definition of Complete items from intent.md addressed
- [ ] No regressions in existing functionality

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] All checks from the review pass
- [ ] Complete implementation confirmed against intent.md checklist
