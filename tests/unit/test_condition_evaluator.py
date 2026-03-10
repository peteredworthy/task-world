"""Tests for the ConditionEvaluator class."""

import pytest

from orchestrator.workflow.condition_evaluator import (
    ConditionEvalError,
    ConditionEvaluator,
    StepOutcome,
    Tokenizer,
    TokenType,
)


class TestTokenizer:
    """Tests for the Tokenizer class."""

    def test_string_literals(self):
        """Test tokenizing string literals."""
        tokenizer = Tokenizer('"hello world"')
        tokens = tokenizer.tokenize()
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_single_quoted_strings(self):
        """Test tokenizing single-quoted strings."""
        tokenizer = Tokenizer("'hello'")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello"

    def test_number_literals(self):
        """Test tokenizing number literals."""
        tokenizer = Tokenizer("42 3.14 -5")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 42
        assert tokens[1].type == TokenType.NUMBER
        assert tokens[1].value == 3.14
        assert tokens[2].type == TokenType.NUMBER
        assert tokens[2].value == -5

    def test_list_literals(self):
        """Test tokenizing list literals."""
        tokenizer = Tokenizer('["a", "b", 1, 2]')
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.LIST
        assert tokens[0].value == ["a", "b", 1, 2]

    def test_empty_list(self):
        """Test tokenizing empty lists."""
        tokenizer = Tokenizer("[]")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.LIST
        assert tokens[0].value == []

    def test_variables(self):
        """Test tokenizing variables."""
        tokenizer = Tokenizer("{{complexity}}")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.VARIABLE
        assert tokens[0].value == "complexity"

    def test_step_outcome(self):
        """Test tokenizing step outcomes."""
        tokenizer = Tokenizer("steps.S-01.has_failures")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.STEP_OUTCOME
        assert tokens[0].value == ("S-01", "has_failures")

    def test_keywords(self):
        """Test tokenizing keywords."""
        tokenizer = Tokenizer("always never manual")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.KEYWORD
        assert tokens[0].value == "always"
        assert tokens[1].type == TokenType.KEYWORD
        assert tokens[1].value == "never"
        assert tokens[2].type == TokenType.KEYWORD
        assert tokens[2].value == "manual"

    def test_operators(self):
        """Test tokenizing operators."""
        tokenizer = Tokenizer("== != in not in and or not")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.EQ
        assert tokens[1].type == TokenType.NEQ
        assert tokens[2].type == TokenType.IN
        assert tokens[3].type == TokenType.NOT_IN
        assert tokens[4].type == TokenType.AND
        assert tokens[5].type == TokenType.OR
        assert tokens[6].type == TokenType.NOT

    def test_parentheses(self):
        """Test tokenizing parentheses."""
        tokenizer = Tokenizer("()")
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[1].type == TokenType.RPAREN

    def test_whitespace_handling(self):
        """Test that whitespace is skipped."""
        tokenizer = Tokenizer('  "hello"   42  ')
        tokens = tokenizer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[1].type == TokenType.NUMBER

    def test_expression_too_long(self):
        """Test that expressions exceeding 500 characters are rejected."""
        long_expr = "x" * 501
        with pytest.raises(ConditionEvalError, match="exceeds maximum length"):
            Tokenizer(long_expr)

    def test_unterminated_string(self):
        """Test that unterminated strings raise error."""
        with pytest.raises(ConditionEvalError, match="Unterminated string"):
            Tokenizer('"hello').tokenize()

    def test_unterminated_variable(self):
        """Test that unterminated variables raise error."""
        with pytest.raises(ConditionEvalError, match="Unterminated variable"):
            Tokenizer("{{hello").tokenize()

    def test_invalid_character(self):
        """Test that invalid characters raise error."""
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            Tokenizer("@invalid").tokenize()

    def test_unterminated_list(self):
        """Test that unterminated lists raise error."""
        with pytest.raises(ConditionEvalError, match="Unterminated list"):
            Tokenizer('["a"').tokenize()


class TestParser:
    """Tests for the Parser class (via ConditionEvaluator)."""

    def test_string_comparison_equal(self):
        """Test string comparison with ==."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"hello" == "hello"', {}, {})
        assert result is True

    def test_string_comparison_not_equal(self):
        """Test string comparison with !=."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"hello" != "world"', {}, {})
        assert result is True

    def test_number_comparison(self):
        """Test number comparison."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("42 == 42", {}, {})
        assert result is True

    def test_variable_substitution(self):
        """Test variable substitution in expressions."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("{{complexity}} == 'high'", {"complexity": "high"}, {})
        assert result is True

    def test_variable_substitution_false(self):
        """Test variable substitution resulting in false."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("{{complexity}} == 'high'", {"complexity": "low"}, {})
        assert result is False

    def test_unknown_variable_is_falsy(self):
        """Test that unknown variables resolve to empty string (falsy)."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("{{unknown}} == ''", {}, {})
        assert result is True

    def test_step_outcome_has_failures(self):
        """Test step outcome resolution."""
        evaluator = ConditionEvaluator()
        outcome = StepOutcome(
            has_failures=True, all_passed=False, any_completed=True, completed=True, skipped=False
        )
        result = evaluator.evaluate("steps.S-01.has_failures", {}, {"S-01": outcome})
        assert result is True

    def test_step_outcome_all_passed(self):
        """Test all_passed step outcome."""
        evaluator = ConditionEvaluator()
        outcome = StepOutcome(
            has_failures=False, all_passed=True, any_completed=True, completed=True, skipped=False
        )
        result = evaluator.evaluate("steps.S-01.all_passed", {}, {"S-01": outcome})
        assert result is True

    def test_step_outcome_completed(self):
        """Test completed step outcome."""
        evaluator = ConditionEvaluator()
        outcome = StepOutcome(
            has_failures=False, all_passed=True, any_completed=True, completed=True, skipped=False
        )
        result = evaluator.evaluate("steps.S-01.completed", {}, {"S-01": outcome})
        assert result is True

    def test_step_outcome_skipped(self):
        """Test skipped step outcome."""
        evaluator = ConditionEvaluator()
        outcome = StepOutcome(
            has_failures=False, all_passed=True, any_completed=False, completed=False, skipped=True
        )
        result = evaluator.evaluate("steps.S-01.skipped", {}, {"S-01": outcome})
        assert result is True

    def test_and_operator(self):
        """Test and operator."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 1 and 2 == 2", {}, {})
        assert result is True

    def test_and_operator_false(self):
        """Test and operator with false condition."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 1 and 2 == 3", {}, {})
        assert result is False

    def test_or_operator(self):
        """Test or operator."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 2 or 2 == 2", {}, {})
        assert result is True

    def test_or_operator_false(self):
        """Test or operator with false condition."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 2 or 2 == 3", {}, {})
        assert result is False

    def test_not_operator(self):
        """Test not operator."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("not (1 == 2)", {}, {})
        assert result is True

    def test_operator_precedence_and_before_or(self):
        """Test that and binds tighter than or."""
        # (1 == 1 and 1 == 2) or (2 == 2) = False or True = True
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 1 and 1 == 2 or 2 == 2", {}, {})
        assert result is True

    def test_membership_in(self):
        """Test 'in' operator."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"a" in ["a", "b", "c"]', {}, {})
        assert result is True

    def test_membership_in_false(self):
        """Test 'in' operator with false result."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"d" in ["a", "b", "c"]', {}, {})
        assert result is False

    def test_membership_not_in(self):
        """Test 'not in' operator."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"d" not in ["a", "b", "c"]', {}, {})
        assert result is True

    def test_membership_not_in_false(self):
        """Test 'not in' operator with false result."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate('"a" not in ["a", "b", "c"]', {}, {})
        assert result is False

    def test_keyword_always(self):
        """Test 'always' keyword."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("always", {}, {})
        assert result is True

    def test_keyword_never(self):
        """Test 'never' keyword."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("never", {}, {})
        assert result is False

    def test_keyword_manual(self):
        """Test 'manual' keyword."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("manual", {}, {})
        assert result is None

    def test_parenthesized_expression(self):
        """Test parenthesized expressions."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("(1 == 1)", {}, {})
        assert result is True

    def test_nested_parentheses(self):
        """Test deeply nested parentheses."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("((((1 == 1))))", {}, {})
        assert result is True

    def test_complex_expression(self):
        """Test a complex expression."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate(
            '{{status}} == "ready" and ("a" in ["a", "b"] or "c" == "d")', {"status": "ready"}, {}
        )
        assert result is True

    def test_empty_expression(self):
        """Test that empty expressions raise error."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="cannot be empty"):
            evaluator.evaluate("", {}, {})

    def test_max_depth_exceeded(self):
        """Test that deeply nested expressions are rejected."""
        evaluator = ConditionEvaluator()
        # Create expression with more than 10 levels of nesting
        expr = "(" * 15 + "1 == 1" + ")" * 15
        with pytest.raises(ConditionEvalError, match="exceeds maximum depth"):
            evaluator.evaluate(expr, {}, {})

    def test_unexpected_token(self):
        """Test that unexpected tokens raise error."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("1 == 2 extra", {}, {})

    def test_step_outcome_with_dict(self):
        """Test that step outcomes can be dicts as well as StepOutcome objects."""
        evaluator = ConditionEvaluator()
        outcome_dict = {
            "has_failures": True,
            "all_passed": False,
            "any_completed": True,
            "completed": True,
            "skipped": False,
        }
        result = evaluator.evaluate("steps.S-01.has_failures", {}, {"S-01": outcome_dict})
        assert result is True

    def test_missing_step_outcome(self):
        """Test that missing step outcomes resolve to empty string (falsy)."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("steps.S-01.has_failures == ''", {}, {})
        assert result is True

    def test_number_with_variable(self):
        """Test number comparison with variable."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("{{count}} == 5", {"count": 5}, {})
        assert result is True

    def test_list_with_number_membership(self):
        """Test list membership with numbers."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 in [1, 2, 3]", {}, {})
        assert result is True

    def test_and_with_none(self):
        """Test and operator with None (manual) result."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("manual and 1 == 1", {}, {})
        assert result is None

    def test_or_with_none(self):
        """Test or operator with None (manual) result."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("manual or 1 == 1", {}, {})
        assert result is None

    def test_not_with_none(self):
        """Test not operator with None (manual) result."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("not manual", {}, {})
        assert result is None

    def test_case_insensitive_operators(self):
        """Test that operators are case-insensitive."""
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("1 == 1 AND 2 == 2", {}, {})
        assert result is True

    def test_comparison_with_unknown_property(self):
        """Test comparison with unknown step property."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unknown step property"):
            evaluator.evaluate("steps.S-01.unknown_property", {}, {})


class TestSafetyConstraints:
    """Tests for safety constraints to prevent abuse."""

    def test_long_expression_exceeds_500_chars(self):
        """Test that expressions exceeding 500 characters raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        long_expr = "x" * 501
        with pytest.raises(ConditionEvalError, match="exceeds maximum length of 500"):
            evaluator.evaluate(long_expr, {}, {})

    def test_expression_exactly_500_chars_allowed(self):
        """Test that expressions of exactly 500 characters are allowed."""
        evaluator = ConditionEvaluator()
        # Create a 500-character string literal in quotes
        # '"' + 498 chars + '"' = 500 chars total
        expr = '"' + "a" * 498 + '"'
        assert len(expr) == 500
        # Should not raise an exception about exceeding max length
        result = evaluator.evaluate(expr, {}, {})
        # Just verify it evaluates without error (returns False for non-boolean primary)
        assert result is not None

    def test_deeply_nested_parentheses_exceeds_max_depth(self):
        """Test that deeply nested expressions (>10 levels) raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        # Create expression with 11 levels of nesting (more than max_depth=10)
        expr = "(" * 11 + "1 == 1" + ")" * 11
        with pytest.raises(ConditionEvalError, match="exceeds maximum depth of 10"):
            evaluator.evaluate(expr, {}, {})

    def test_nested_parentheses_within_max_depth_allowed(self):
        """Test that nested expressions within max depth are allowed."""
        evaluator = ConditionEvaluator()
        # Create expression with 9 levels of nesting (within max_depth=10)
        expr = "(" * 9 + "1 == 1" + ")" * 9
        result = evaluator.evaluate(expr, {}, {})
        assert result is True

    def test_arbitrary_attribute_access_underscore_class(self):
        """Test that arbitrary attribute access like __class__ raises ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unknown step property"):
            evaluator.evaluate("steps.S-01.__class__", {}, {})

    def test_arbitrary_attribute_access_dunder_dict(self):
        """Test that arbitrary attribute access like __dict__ raises ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unknown step property"):
            evaluator.evaluate("steps.S-01.__dict__", {}, {})

    def test_arbitrary_attribute_access_bases(self):
        """Test that arbitrary attribute access like __bases__ raises ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unknown step property"):
            evaluator.evaluate("steps.S-01.__bases__", {}, {})

    def test_function_call_exec(self):
        """Test that function call attempts like exec() raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("exec('code')", {}, {})

    def test_function_call_eval(self):
        """Test that function call attempts like eval() raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("eval('code')", {}, {})

    def test_function_call_getattr(self):
        """Test that function call attempts like getattr() raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("getattr(steps.S-01, '__class__')", {}, {})

    def test_function_call_import(self):
        """Test that function call attempts like __import__() raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("__import__('os')", {}, {})

    def test_builtin_identifier_not_allowed(self):
        """Test that arbitrary built-in function names raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("len", {}, {})

    def test_builtin_identifier_with_parentheses(self):
        """Test that arbitrary identifiers with parentheses raise ConditionEvalError."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("foo()", {}, {})

    def test_chained_attribute_access_rejected(self):
        """Test that chained attribute access beyond pattern is rejected."""
        evaluator = ConditionEvaluator()
        # Chained access is rejected at tokenization level (extra dot is unexpected)
        with pytest.raises(ConditionEvalError, match="Unexpected character"):
            evaluator.evaluate("steps.S-01.all_passed.some_attr", {}, {})

    def test_malformed_step_reference_no_property(self):
        """Test that step references without property raise error."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Missing property"):
            evaluator.evaluate("steps.S-01.", {}, {})

    def test_malformed_step_reference_no_dot(self):
        """Test that step references without dot raise error."""
        evaluator = ConditionEvaluator()
        with pytest.raises(ConditionEvalError, match="Expected '\\.' after step ID"):
            evaluator.evaluate("steps.S-01 all_passed", {}, {})

    def test_allowed_properties_only(self):
        """Test that only allowed properties are recognized."""
        evaluator = ConditionEvaluator()
        allowed_props = ["has_failures", "all_passed", "any_completed", "completed", "skipped"]

        # All allowed properties should parse without error when used correctly
        outcome = {
            "has_failures": False,
            "all_passed": True,
            "any_completed": True,
            "completed": True,
            "skipped": False,
        }
        for prop in allowed_props:
            result = evaluator.evaluate(f"steps.S-01.{prop}", {}, {"S-01": outcome})
            assert isinstance(result, bool)

        # Disallowed properties should raise
        with pytest.raises(ConditionEvalError, match="Unknown step property"):
            evaluator.evaluate("steps.S-01.disallowed_prop", {}, {})
