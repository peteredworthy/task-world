# Step Plan: Safe Condition Evaluator

## Purpose

Build the `ConditionEvaluator` class -- a safe expression parser and evaluator using recursive descent. This is the highest-risk component (expression parsing) so it is built and tested first in complete isolation, with no dependencies on other new code.

## Prerequisites

- None -- this is the first step with no dependencies.

## Functional Contract

### Inputs

- `expression: str` -- a condition expression string (e.g., `{{complexity}} == 'high'`, `steps.S-01.has_failures`, `always`, `manual`)
- `variables: dict[str, Any]` -- run config variables and repeat-for item variables for `{{var}}` resolution
- `step_outcomes: dict[str, StepOutcome]` -- completed step outcomes for `steps.S-XX.property` resolution

### Outputs

- `True` -- condition is met, step should execute
- `False` -- condition is not met, step should be skipped
- `None` -- manual gate, requires user input to proceed
- Raises `ConditionEvalError` for malformed or unsafe expressions

### Error Cases

- Expression exceeds 500 characters -- raises `ConditionEvalError`
- Parse depth exceeds 10 levels -- raises `ConditionEvalError`
- Unknown/unsupported operator or syntax -- raises `ConditionEvalError`
- Attribute access beyond allowed `steps.{id}.{property}` pattern -- raises `ConditionEvalError`
- Function call attempts -- raises `ConditionEvalError`
- Unknown variables resolve to empty string (falsy), not an error

## Tasks

1. Create `src/orchestrator/workflow/condition_evaluator.py` with:
   - `ConditionEvalError` exception class
   - `StepOutcome` Pydantic model with 5 properties: `has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`
   - `ConditionEvaluator` class with `evaluate()` method
2. Implement tokenizer/lexer for the supported grammar:
   - Operators: `==`, `!=`, `in`, `not in`, `and`, `or`, `not`
   - Literals: strings (single/double quoted), numbers, booleans (`true`/`false`), lists (`[a, b, c]`)
   - Variables: `{{var_name}}` template syntax
   - Step outcomes: `steps.S-XX.property` dot notation
   - Keywords: `always`, `never`, `manual`
   - Grouping: parentheses `()`
3. Implement recursive descent parser following the grammar:
   ```
   expr     -> or_expr
   or_expr  -> and_expr ("or" and_expr)*
   and_expr -> not_expr ("and" not_expr)*
   not_expr -> "not" not_expr | compare
   compare  -> primary (("==" | "!=" | "in" | "not" "in") primary)?
   primary  -> STRING | NUMBER | BOOL | LIST | VARIABLE | "(" expr ")"
   ```
4. Implement safety constraints (max length, max depth, allowlisted attributes)
5. Create `tests/unit/test_condition_evaluator.py` with comprehensive tests:
   - String comparison (`==`, `!=`)
   - Variable substitution with `{{var}}`
   - Output-based conditions (`steps.S-01.has_failures`, `.completed`, `.skipped`)
   - Boolean operators (`and`, `or`, `not`) with precedence
   - Membership operators (`in`, `not in`) with lists
   - Literal keywords (`always` -> True, `never` -> False, `manual` -> None)
   - Edge cases: empty expression, unknown variable (falsy), deeply nested parens
   - Safety: expressions > 500 chars rejected, disallowed attribute access, no code execution
   - Syntax errors: malformed expressions raise `ConditionEvalError`

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_condition_evaluator.py -v` -- all tests pass
- `uv run pyright src/orchestrator/workflow/condition_evaluator.py` -- no type errors
- No existing tests broken (`uv run pytest tests/unit/ -v` still passes)

### Manual Verification

- Review that no use of `eval()`, `exec()`, or `ast.literal_eval()` exists in the evaluator
- Confirm adversarial inputs (code injection attempts, deeply nested expressions) are rejected

## Context & References

- Plan: `docs/conditional-steps/plan.md` -- Step 1 specification
- Architecture: `docs/conditional-steps/architecture.md` -- `ConditionEvaluator` interface and grammar
- Clarification Q3: Syntax errors pause the run (evaluator raises `ConditionEvalError`)
- Clarification Q5: 5 step outcome properties (`has_failures`, `all_passed`, `any_completed`, `completed`, `skipped`)
