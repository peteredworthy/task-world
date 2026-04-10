# Step 06: Validation and Cleanup

This step finalizes the single-queue signal model implementation by running the complete test suite, removing dead code from the old dual-path routing logic, and verifying that every intent item [I-01] through [I-36] has been addressed by at least one of the preceding implementation steps. No new functionality is produced; this step confirms correctness and cleanliness of the overall implementation.

## Intent Verification

**Original Intent**: [I-21] Final validation; [I-34] No legacy routing code; [I-36] Traceability audit

**Functionality to Produce**:
- All backend unit tests pass
- All backend integration tests pass
- All frontend tests pass
- Type checker output is clean (`tsc --noEmit`)
- Linter output is clean (`eslint`, `ruff`)
- All legacy dual-path routing code and dead helpers removed
- No-op `handle_resume` logging removed from `RunWorkflow`
- Traceability matrix confirms every intent item is covered by at least one step

**Final Verification Criteria**:
- `pytest tests/` completes with all tests passing
- Frontend test suite passes with no errors
- Type checking and linting report no errors
- Grep confirms no occurrences of removed patterns (e.g., `has_active_workflow` in service layer)
- Traceability spreadsheet/document maps every [I-XX] to step(s) that implement it

---

## Task 1: Run Backend Unit and Integration Test Suite

**Description**: Execute the full backend test suite to confirm that all signal-queue implementation changes (Steps 01–05) do not break existing tests and all new tests pass.

**Implementation Plan (Do These Steps)**

This task runs the complete test suite from the project root to verify that all 2557+ backend tests pass without errors or warnings.

- [ ] From `/Users/peter/code/task-world/worktrees/r53`, run the backend test suite:
```bash
cd /Users/peter/code/task-world/worktrees/r53
uv run pytest tests/ -v --tb=short 2>&1 | tee test-output.log
```

- [ ] Verify the test run completed and capture the summary. The output should show:
  - Total test count (expected: ~2557 or higher from prior baselines)
  - Pass count (expected: all tests pass)
  - Failure count (expected: 0)
  - Skipped/warning counts are acceptable, but no failures

- [ ] Inspect the log for any test failures. If failures are found, note their names and error messages for debugging before proceeding to Task 2.

- [ ] If all tests pass, document the pass count and move to the next task.

**Dependencies**
- Steps 01–05 must be complete with all code changes applied.
- `uv` and Python environment must be set up and accessible.
- Database must be initialized (or test suite initializes it).

**References**
- Project test baseline (from MEMORY.md): 2557 backend tests pass post wiring-fix
- pytest documentation: https://docs.pytest.org/en/stable/usage.html

**Constraints**
- Only the backend test suite is run in this task. Frontend tests are Task 2.
- Test output must be captured and preserved (saved to `test-output.log` for review).
- No code changes are made during this task. This is verification only.

**Side Effects**
- Test database may be created or modified (in-memory or temporary file). This is expected.

**Functionality (Expected Outcomes)**
- [ ] All backend unit tests pass
- [ ] All backend integration tests pass
- [ ] No test failures, errors, or exceptions
- [ ] Test output log is available for review

**Final Verification (Proof of Completion)**

DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run `tail test-output.log` and confirm the final line shows `passed` with a count of all passing tests.
- [ ] Run `grep -i "failed\|error" test-output.log` and confirm no matches (zero failures/errors).
- [ ] Run `uv run pytest tests/ --co -q 2>&1 | wc -l` to confirm the test count is approximately 2557 or higher.
- [ ] Document the exact pass count in this task's completion note.

---

## Task 2: Run Frontend Test Suite

**Description**: Execute the full frontend test suite to confirm that the addition of `STOPPING` status to the `RunStatus` enum and any corresponding UI changes do not break existing tests.

**Implementation Plan (Do These Steps)**

This task runs the React/frontend test suite from the `ui/` directory.

- [ ] Navigate to the frontend directory and run the test suite:
```bash
cd /Users/peter/code/task-world/worktrees/r53/ui
npm test -- --watchAll=false --passWithNoTests 2>&1 | tee ../frontend-test-output.log
```

- [ ] Verify the test run completed. The output should show:
  - Total test files executed
  - Total test count
  - Pass count (expected: all tests pass, baseline ~221 from MEMORY.md)
  - Failure count (expected: 0)

- [ ] If test failures are found, note them for debugging.

- [ ] If all tests pass, document the count and move to Task 3.

**Dependencies**
- `npm` and Node.js must be installed and configured.
- All code changes from Steps 01–05 must be in place.
- Frontend dependencies (`node_modules`) must be installed (run `npm install` if needed beforehand).

**References**
- Project frontend test baseline (from MEMORY.md): 221 tests pass (26 test files)
- React Testing Library docs: https://testing-library.com/docs/react-testing-library/intro/

**Constraints**
- Frontend tests only. Backend tests are covered in Task 1.
- Test output is saved to `frontend-test-output.log` for review.
- No code changes during this task.

**Side Effects**
- None beyond normal test execution artifacts.

**Functionality (Expected Outcomes)**
- [ ] All frontend tests pass
- [ ] No test failures or errors
- [ ] `STOPPING` status enum change does not break UI tests

**Final Verification (Proof of Completion)**

DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run `tail ../frontend-test-output.log` and confirm the final summary shows all tests passing.
- [ ] Run `grep -i "failed\|error" ../frontend-test-output.log` and confirm no matches.
- [ ] Document the exact pass count from the test output.

---

## Task 3: Run Type Checker and Linter

**Description**: Execute TypeScript type checking and ESLint linting to ensure no type errors or style violations were introduced in Steps 01–05.

**Implementation Plan (Do These Steps)**

This task validates the TypeScript and JavaScript code quality.

- [ ] From the `ui/` directory, run the TypeScript type checker:
```bash
cd /Users/peter/code/task-world/worktrees/r53/ui
npx tsc --noEmit 2>&1 | tee ../typescript-output.log
```

- [ ] Verify the type checker completed. Expected result: no errors (exit code 0).

- [ ] From the `ui/` directory, run the ESLint linter:
```bash
npx eslint src/ --ext .ts,.tsx 2>&1 | tee ../eslint-output.log
```

- [ ] Verify the linter completed. Expected result: no errors (exit code 0, or only warnings if acceptable).

- [ ] From the project root, run the Python linter (ruff) on backend code:
```bash
cd /Users/peter/code/task-world/worktrees/r53
uv run ruff check src/ scripts/ tests/ 2>&1 | tee ruff-output.log
```

- [ ] Verify ruff completed with no errors. If ruff suggests fixes, review and apply them:
```bash
uv run ruff check src/ scripts/ tests/ --fix
```

- [ ] Run ruff again to confirm all fixes were applied:
```bash
uv run ruff check src/ scripts/ tests/ 2>&1 | tee ruff-output-final.log
```

**Dependencies**
- `npm` and Node.js must be installed (for TypeScript and ESLint).
- `uv` must be installed (for Python linting).
- All code changes from Steps 01–05 must be in place.

**References**
- TypeScript compiler: https://www.typescriptlang.org/docs/handbook/compiler-options.html
- ESLint docs: https://eslint.org/docs/latest/
- Ruff docs: https://docs.astral.sh/ruff/

**Constraints**
- Type check must pass with **zero errors** (no ignoring or suppressing).
- Linting should pass with zero errors. Warnings may be acceptable if pre-existing.
- No code changes beyond what ruff --fix applies.

**Side Effects**
- Ruff may auto-fix formatting issues. Review these changes before committing.

**Functionality (Expected Outcomes)**
- [ ] TypeScript compiler reports no errors
- [ ] ESLint reports no errors (or only pre-existing warnings)
- [ ] Python linter (ruff) reports no errors
- [ ] All linting output is logged for review

**Final Verification (Proof of Completion)**

DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run `cat ../typescript-output.log` and confirm the output is empty or shows only the success message.
- [ ] Run `cat ../eslint-output.log` and confirm no errors are reported.
- [ ] Run `cat ruff-output-final.log` and confirm no errors are reported.
- [ ] Run `tsc --noEmit; echo $?` and confirm exit code is 0.
- [ ] Run `npx eslint src/ --ext .ts,.tsx; echo $?` and confirm exit code is 0.
- [ ] Run `uv run ruff check src/ scripts/ tests/; echo $?` and confirm exit code is 0.

---

## Task 4: Audit and Remove Dead Code

**Description**: Identify and remove dead code from the old dual-path routing logic, specifically the no-op `handle_resume` log in `RunWorkflow` and any other legacy patterns that are no longer used.

**Implementation Plan (Do These Steps)**

This task removes code that was part of the old `has_active_workflow` branching but is no longer needed.

- [ ] Search for the no-op `handle_resume` log message in `RunWorkflow`:
```bash
cd /Users/peter/code/task-world/worktrees/r53
grep -n "handle_resume" src/orchestrator/workflow/run_workflow.py
```

- [ ] If found, open `src/orchestrator/workflow/run_workflow.py` and locate the `handle_resume()` method. Identify any logging statement that is a no-op (e.g., a bare `logger.info("resumed")` with no action).

- [ ] Remove the no-op log statement(s) from `handle_resume()`. If the entire method body becomes empty (only docstring), keep the method but ensure it has a clear docstring explaining it is called but performs no action. Or, if the method is never called, remove it entirely and any references to it.

- [ ] Search for any other dead patterns from the old routing:
```bash
# Check for unused direct spawn_run calls in service layer
grep -n "spawn_run" src/orchestrator/workflow/service.py
# Check for has_active_workflow calls in places other than consumer
grep -rn "has_active_workflow" src/ --include="*.py" | grep -v "test" | grep -v "consumer.py"
```

- [ ] For any matches found, verify they are truly dead (not called by the new signal-based flow). If they are dead, remove them.

- [ ] Search for any unused imports related to the old routing:
```bash
# Look for imports that may no longer be used
grep -n "from.*import.*register_active_run\|from.*import.*unregister_active_run" src/orchestrator/workflow/service.py
```

- [ ] Remove any such imports that are no longer used.

- [ ] Run a final comprehensive check for any remaining signs of the old branching:
```bash
grep -rn "if.*has_active_workflow" src/orchestrator/workflow/ --include="*.py" | grep -v "test" | grep -v "consumer.py"
```

- [ ] If any matches remain, review and remove the dead branch or the entire condition if both branches are now the same.

**Dependencies**
- Steps 01–05 must be complete so that the old patterns are actually unused.

**References**
- See `src/orchestrator/workflow/service.py` and `src/orchestrator/workflow/run_workflow.py` for context on old routing patterns.

**Constraints**
- Only remove code that is confirmed dead (not called by the new flow).
- Do not remove code that is part of the new signal-queue implementation.
- Do not modify test code unless the tests explicitly test dead code (in which case, update the tests or remove them).

**Side Effects**
- Removal of dead code reduces file size and improves readability, but may require updating any test mocks that referenced the removed code.

**Functionality (Expected Outcomes)**
- [ ] No-op `handle_resume` log is removed from `RunWorkflow`
- [ ] No dead `spawn_run` calls remain in service layer
- [ ] No `has_active_workflow` checks remain outside consumer.py and tests
- [ ] No unused imports from the old routing logic
- [ ] All code that remains is part of the active signal-queue flow

**Final Verification (Proof of Completion)**

DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run `grep -n "handle_resume" src/orchestrator/workflow/run_workflow.py` and confirm it shows only method definition (if kept) or no output (if removed).
- [ ] Run `grep -rn "spawn_run" src/orchestrator/workflow/service.py` and confirm no matches or only comments.
- [ ] Run `grep -rn "has_active_workflow" src/orchestrator/workflow/ --include="*.py" | grep -v "test" | grep -v "consumer.py"` and confirm zero matches.
- [ ] Run `uv run pytest tests/ -v --tb=short` again to confirm no tests were broken by dead code removal (expected: same pass count as Task 1).

---

## Task 5: Verify Traceability and Document Coverage

**Description**: Confirm that every intent item [I-01] through [I-36] from `docs/single-queue/intent.md` is addressed by at least one of Steps 01–05, and document this mapping.

**Implementation Plan (Do These Steps)**

This task creates a traceability matrix confirming coverage of all intent items.

- [ ] Open `docs/single-queue/intent.md` and extract all intent item identifiers [I-XX]. Verify the count is 36 items.

- [ ] Create a traceability spreadsheet or document at `docs/single-queue/traceability.md`:
```bash
cd /Users/peter/code/task-world/worktrees/r53
touch docs/single-queue/traceability.md
```

- [ ] In the document, create a table with columns: `Intent ID`, `Description`, `Addressed in Step(s)`, `Status`. Example:
```markdown
| Intent ID | Description | Addressed in Step(s) | Status |
|-----------|-------------|----------------------|--------|
| [I-01]    | Single queue instead of two paths | S-03 (rewire start_run) | ✓ |
| [I-02]    | Consumer polls pending_signals | S-02 (consumer module) | ✓ |
| ...       | ...                             | ...                     | ... |
```

- [ ] For each intent item, review the step plans (S-01 through S-05) and note which step(s) directly implement or enable that item. Consult the "Traces to" section in the plan for each step.

- [ ] Fill in the entire table, ensuring every [I-XX] is listed with at least one step.

- [ ] Review the completed table and verify:
  - All 36 intent items are listed
  - Every item has at least one "Addressed in Step(s)" entry
  - No items are marked as NOT COVERED (or if any are, document the reason why they are deferred/not required)

- [ ] Save the document and commit it:
```bash
git add docs/single-queue/traceability.md
git commit -m "Add traceability matrix for single-queue signal model implementation"
```

**Dependencies**
- `docs/single-queue/intent.md` must exist and be complete (36 items).
- Steps 01–05 must be documented in `docs/single-queue/plan.md` with clear "Traces to" sections.

**References**
- Intent document: `docs/single-queue/intent.md`
- Step plan: `docs/single-queue/plan.md`

**Constraints**
- Every intent item [I-01] through [I-36] must be accounted for.
- If an item is not covered by Steps 01–05, it must be explicitly noted as deferred (with justification) or the implementation is incomplete.

**Side Effects**
- Creates new document `traceability.md` for future reference and audit.

**Functionality (Expected Outcomes)**
- [ ] Traceability document created with all 36 intent items listed
- [ ] Each item maps to one or more steps
- [ ] All mappings are accurate and verified
- [ ] Document is committed to git

**Final Verification (Proof of Completion)**

DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run `wc -l docs/single-queue/traceability.md` and confirm the document exists and has content.
- [ ] Run `grep -c "\[I-" docs/single-queue/traceability.md` and confirm it shows 36 matches (all intent items referenced).
- [ ] Run `grep -E "\[I-[0-9]+\].*NOT COVERED|DEFERRED" docs/single-queue/traceability.md` and confirm any deferred items are justified in the same document.
- [ ] Run `git log --oneline docs/single-queue/traceability.md | head -1` and confirm the document was committed.
- [ ] Manually review the traceability document to ensure each mapping is accurate.

---

## Final Completion Check

Once all five tasks are complete:

1. **All tests pass** (Tasks 1–2): Backend and frontend test suites run without failure.
2. **Type and style checks clean** (Task 3): No errors from TypeScript, ESLint, or Ruff.
3. **Dead code removed** (Task 4): Legacy routing patterns are eliminated.
4. **Traceability verified** (Task 5): Every intent item is accounted for.

At this point, the single-queue signal model implementation is complete, validated, and ready for deployment.
