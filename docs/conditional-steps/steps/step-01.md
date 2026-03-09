# Step 1: Safe Condition Evaluator

Build the `ConditionEvaluator` class -- a safe expression parser and evaluator using recursive descent. This is the highest-risk component (expression parsing) so it is built and tested first in complete isolation, with no dependencies on other new code.

## Intent Verification
**Original Intent**: Create a safe, dependency-free expression evaluator that can determine whether a step should execute, be skipped, or require manual approval (see `docs/conditional-steps/intent.md`).
**Functionality to Produce**:
- `ConditionEvaluator` class in `src/orchestrator/workflow/condition_evaluator.py`
- `StepOutcome` Pydantic model with 5 properties
- `ConditionEvalError` exception class
- Recursive descent parser supporting `==`, `!=`, `in`, `not in`, `and`, `or`, `not`
- Variable resolution via `{{var}}` and `steps.S-XX.property`
- Keywords: `always` (True), `never` (False), `manual` (None)
- Safety constraints: max 500 chars, max 10 depth, allowlisted attributes only

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_condition_evaluator.py -v` -- all tests pass
- `uv run pyright src/orchestrator/workflow/condition_evaluator.py` -- no type errors
- No existing tests broken (`uv run pytest tests/unit/ -v` still passes)
- No use of `eval()`, `exec()`, or `ast.literal_eval()` in the evaluator

---

## Task 1: Create ConditionEvaluator Module with Core Types

**Description**: Create the new module file with `ConditionEvalError`, `StepOutcome`, and the `ConditionEvaluator` class skeleton with its `evaluate()` method signature.

**Implementation Plan (Do These Steps)**
- [ ] Create `src/orchestrator/workflow/condition_evaluator.py`
- [ ] Define `ConditionEvalError(Exception)` with a message
- [ ] Define `StepOutcome(BaseModel)` with 5 boolean properties: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`
- [ ] Define `ConditionEvaluator` class with `evaluate(expression, variables, step_outcomes) -> bool | None` method

**Dependencies**
- None -- this is the first task

**References**
- `docs/conditional-steps/architecture.md` -- `ConditionEvaluator` interface and `StepOutcome` definition
- `docs/conditional-steps/step-01-plan.md` -- full task specification
- Clarification Q5: 5 step outcome properties (`has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`)

**Constraints**
- No external dependencies -- pure Python + Pydantic only
- No `eval()`, `exec()`, or `ast.literal_eval()`

**Functionality (Expected Outcomes)**
- [ ] `ConditionEvalError` is importable and can be raised with a message
- [ ] `StepOutcome` validates with all 5 boolean fields
- [ ] `ConditionEvaluator.evaluate()` has correct type signature

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.condition_evaluator import ConditionEvaluator, ConditionEvalError, StepOutcome; print('OK')"` succeeds
- [ ] `uv run pyright src/orchestrator/workflow/condition_evaluator.py` -- no errors

---

## Task 2: Implement Tokenizer and Recursive Descent Parser

**Description**: Implement the tokenizer/lexer and recursive descent parser for the supported expression grammar.

**Implementation Plan (Do These Steps)**
- [ ] Implement tokenizer that produces tokens for: operators (`==`, `!=`, `in`, `not in`, `and`, `or`, `not`), literals (strings, numbers, booleans, lists), variables (`{{var}}`), step outcomes (`steps.S-XX.property`), keywords (`always`, `never`, `manual`), grouping (`(`, `)`)
- [ ] Implement recursive descent parser following the grammar:
  ```
  expr     -> or_expr
  or_expr  -> and_expr ("or" and_expr)*
  and_expr -> not_expr ("and" not_expr)*
  not_expr -> "not" not_expr | compare
  compare  -> primary (("==" | "!=" | "in" | "not" "in") primary)?
  primary  -> STRING | NUMBER | BOOL | LIST | VARIABLE | "(" expr ")"
  ```
- [ ] Implement variable resolution: `{{var_name}}` from `variables` dict, `steps.S-XX.property` from `step_outcomes` dict
- [ ] Implement keyword evaluation: `always` -> True, `never` -> False, `manual` -> None

**Dependencies**
- [ ] Task 1 must be complete (class skeleton exists)

**References**
- `docs/conditional-steps/architecture.md` -- grammar specification and variable resolution rules
- `docs/conditional-steps/step-01-plan.md` -- tasks 2-3

**Constraints**
- Unknown variables resolve to empty string (falsy), not an error
- Only `steps.{id}.{property}` attribute access allowed, where property is one of: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`
- No function calls allowed in expressions

**Functionality (Expected Outcomes)**
- [ ] Expressions like `{{complexity}} == 'high'` evaluate correctly
- [ ] Boolean operators work with correct precedence (`and` binds tighter than `or`)
- [ ] `steps.S-01.has_failures` resolves from step_outcomes dict
- [ ] `always`, `never`, `manual` keywords return True, False, None respectively

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.workflow.condition_evaluator import ConditionEvaluator; e = ConditionEvaluator(); print(e.evaluate('always', {}, {}))"` prints `True`

---

## Task 3: Implement Safety Constraints

**Description**: Add safety constraints to prevent abuse: max expression length, max parse depth, and reject unsafe patterns.

**Implementation Plan (Do These Steps)**
- [ ] Add max expression length check (500 characters) -- raise `ConditionEvalError` if exceeded
- [ ] Add max parse depth check (10 levels) -- raise `ConditionEvalError` if exceeded
- [ ] Reject attribute access beyond allowed `steps.{id}.{property}` pattern
- [ ] Reject function call attempts
- [ ] Ensure malformed expressions raise `ConditionEvalError` with descriptive messages

**Dependencies**
- [ ] Task 2 must be complete (parser exists to add constraints to)

**References**
- `docs/conditional-steps/architecture.md` -- safety constraints section
- `docs/conditional-steps/step-01-plan.md` -- task 4
- Clarification Q3: Syntax errors pause the run (evaluator raises `ConditionEvalError`)

**Constraints**
- Errors must include descriptive messages for debugging

**Functionality (Expected Outcomes)**
- [ ] Expressions > 500 chars are rejected
- [ ] Deeply nested expressions beyond depth 10 are rejected
- [ ] Arbitrary attribute access (e.g., `steps.S-01.__class__`) raises error
- [ ] Function calls (e.g., `exec('code')`) raise error

**Final Verification (Proof of Completion)**
- [ ] All safety checks raise `ConditionEvalError` with meaningful messages
- [ ] `grep -rn "eval(\|exec(\|literal_eval" src/orchestrator/workflow/condition_evaluator.py` returns no hits

---

## Task 4: Write Comprehensive Unit Tests

**Description**: Create thorough unit tests covering all expression types, operator precedence, edge cases, and adversarial inputs.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_condition_evaluator.py`
- [ ] Test string comparison: `==`, `!=`
- [ ] Test variable substitution with `{{var}}`
- [ ] Test output-based conditions: `steps.S-01.has_failures`, `.all_passed`, `.any_completed`, `.completed`, `.skipped`
- [ ] Test boolean operators: `and`, `or`, `not` with operator precedence
- [ ] Test membership operators: `in`, `not in` with lists
- [ ] Test literal keywords: `always` -> True, `never` -> False, `manual` -> None
- [ ] Test edge cases: empty expression, unknown variable (falsy), deeply nested parens
- [ ] Test safety: expressions > 500 chars rejected, disallowed attribute access, no code execution
- [ ] Test syntax errors: malformed expressions raise `ConditionEvalError`

**Dependencies**
- [ ] Tasks 1-3 must be complete (evaluator fully implemented)

**References**
- `docs/conditional-steps/architecture.md` -- testing strategy, unit tests section
- `docs/conditional-steps/step-01-plan.md` -- task 5

**Constraints**
- No mocking -- test the real evaluator with real inputs
- Tests must be deterministic and fast (<1s each)

**Functionality (Expected Outcomes)**
- [ ] All expression types have at least one test
- [ ] Adversarial inputs are tested (code injection, extreme nesting)
- [ ] Error messages are verified in safety tests

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_condition_evaluator.py -v` -- all tests pass
- [ ] `uv run pytest tests/unit/ -v` -- no existing tests broken
