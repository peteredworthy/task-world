"""Safe expression parser and evaluator using recursive descent.

This module provides a safe way to evaluate conditional expressions
without risky built-in functions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel


class ConditionEvalError(Exception):
    """Raised when condition evaluation fails."""

    def __init__(self, message: str):
        """Initialize the exception with a message.

        Args:
            message: Description of the evaluation error.
        """
        self.message = message
        super().__init__(self.message)


class StepOutcome(BaseModel):
    """Represents the outcome state of a step.

    Attributes:
        has_failures: Whether the step contains any failed tasks.
        all_passed: Whether all tasks in the step passed.
        any_completed: Whether any task in the step is completed.
        completed: Whether the step itself is completed.
        skipped: Whether the step was skipped.
    """

    has_failures: bool
    all_passed: bool
    any_completed: bool
    completed: bool
    skipped: bool


class TokenType(Enum):
    """Token types for the expression parser."""

    STRING = "STRING"
    NUMBER = "NUMBER"
    BOOL = "BOOL"
    LIST = "LIST"
    VARIABLE = "VARIABLE"
    STEP_OUTCOME = "STEP_OUTCOME"
    KEYWORD = "KEYWORD"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    EQ = "EQ"
    NEQ = "NEQ"
    IN = "IN"
    NOT_IN = "NOT_IN"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    EOF = "EOF"


@dataclass
class Token:
    """Represents a single token in the expression."""

    type: TokenType
    value: Any
    position: int


class Tokenizer:
    """Tokenizes condition expressions."""

    def __init__(self, expression: str):
        """Initialize the tokenizer with an expression string.

        Args:
            expression: The expression to tokenize.

        Raises:
            ConditionEvalError: If expression exceeds 500 characters.
        """
        if len(expression) > 500:
            raise ConditionEvalError("Expression exceeds maximum length of 500 characters")
        self.expression = expression
        self.position = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the expression.

        Returns:
            List of tokens.

        Raises:
            ConditionEvalError: If tokenization fails.
        """
        while self.position < len(self.expression):
            self._skip_whitespace()
            if self.position >= len(self.expression):
                break

            if self._try_string():
                continue
            if self._try_number():
                continue
            if self._try_list():
                continue
            if self._try_variable():
                continue
            if self._try_step_outcome():
                continue
            if self._try_keyword_or_operator():
                continue
            if self._try_parentheses():
                continue
            if self._try_brackets():
                continue
            if self._try_comma():
                continue

            raise ConditionEvalError(
                f"Unexpected character at position {self.position}: '{self.expression[self.position]}'"
            )

        self.tokens.append(Token(TokenType.EOF, None, self.position))
        return self.tokens

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.position < len(self.expression) and self.expression[self.position].isspace():
            self.position += 1

    def _try_string(self) -> bool:
        """Try to parse a string literal."""
        if self.position >= len(self.expression):
            return False

        char = self.expression[self.position]
        if char not in ('"', "'"):
            return False

        quote = char
        start = self.position
        self.position += 1

        while self.position < len(self.expression):
            if self.expression[self.position] == quote:
                self.position += 1
                value = self.expression[start + 1 : self.position - 1]
                self.tokens.append(Token(TokenType.STRING, value, start))
                return True
            if self.expression[self.position] == "\\":
                self.position += 2
            else:
                self.position += 1

        raise ConditionEvalError(f"Unterminated string at position {start}")

    def _try_number(self) -> bool:
        """Try to parse a number literal."""
        if self.position >= len(self.expression):
            return False

        start = self.position
        if self.expression[self.position] == "-":
            self.position += 1

        if self.position >= len(self.expression) or not self.expression[self.position].isdigit():
            self.position = start
            return False

        while self.position < len(self.expression) and self.expression[self.position].isdigit():
            self.position += 1

        if self.position < len(self.expression) and self.expression[self.position] == ".":
            self.position += 1
            while self.position < len(self.expression) and self.expression[self.position].isdigit():
                self.position += 1

        value_str = self.expression[start : self.position]
        value = float(value_str) if "." in value_str else int(value_str)
        self.tokens.append(Token(TokenType.NUMBER, value, start))
        return True

    def _try_list(self) -> bool:
        """Try to parse a list literal [...]."""
        if self.position >= len(self.expression) or self.expression[self.position] != "[":
            return False

        start = self.position
        self.position += 1
        items: list[Any] = []

        self._skip_whitespace()
        if self.position < len(self.expression) and self.expression[self.position] == "]":
            self.position += 1
            self.tokens.append(Token(TokenType.LIST, items, start))
            return True

        while self.position < len(self.expression):
            self._skip_whitespace()

            if self._try_string():
                items.append(self.tokens[-1].value)
                self.tokens.pop()
            elif self._try_number():
                items.append(self.tokens[-1].value)
                self.tokens.pop()
            else:
                raise ConditionEvalError(f"Invalid item in list at position {self.position}")

            self._skip_whitespace()
            if self.position >= len(self.expression):
                raise ConditionEvalError("Unterminated list")

            if self.expression[self.position] == "]":
                self.position += 1
                self.tokens.append(Token(TokenType.LIST, items, start))
                return True

            if self.expression[self.position] == ",":
                self.position += 1
            else:
                raise ConditionEvalError(f"Expected ',' or ']' in list at position {self.position}")

        raise ConditionEvalError("Unterminated list")

    def _try_variable(self) -> bool:
        """Try to parse a variable {{var_name}}."""
        if (
            self.position + 1 >= len(self.expression)
            or self.expression[self.position : self.position + 2] != "{{"
        ):
            return False

        start = self.position
        self.position += 2

        while self.position < len(self.expression) and self.expression[self.position] not in ("}",):
            self.position += 1

        if (
            self.position + 1 >= len(self.expression)
            or self.expression[self.position : self.position + 2] != "}}"
        ):
            raise ConditionEvalError(f"Unterminated variable at position {start}")

        var_name = self.expression[start + 2 : self.position]
        self.position += 2
        self.tokens.append(Token(TokenType.VARIABLE, var_name, start))
        return True

    def _try_step_outcome(self) -> bool:
        """Try to parse a step outcome reference like steps.S-01.has_failures."""
        if self.position >= len(self.expression) or not self.expression[self.position :].startswith(
            "steps."
        ):
            return False

        start = self.position
        self.position += 6

        step_id_start = self.position
        while self.position < len(self.expression) and self.expression[self.position] not in (
            ".",
            " ",
            "(",
            ")",
            ",",
            "]",
        ):
            self.position += 1

        if self.position == step_id_start:
            raise ConditionEvalError(f"Missing step ID at position {start}")

        step_id = self.expression[step_id_start : self.position]

        if self.position >= len(self.expression) or self.expression[self.position] != ".":
            raise ConditionEvalError(f"Expected '.' after step ID at position {self.position}")

        self.position += 1

        prop_start = self.position
        while (
            self.position < len(self.expression)
            and self.expression[self.position].isalnum()
            or (self.position < len(self.expression) and self.expression[self.position] == "_")
        ):
            self.position += 1

        if self.position == prop_start:
            raise ConditionEvalError(f"Missing property at position {self.position}")

        property_name = self.expression[prop_start : self.position]

        if property_name not in (
            "has_failures",
            "all_passed",
            "any_completed",
            "completed",
            "skipped",
        ):
            raise ConditionEvalError(f"Unknown step property: {property_name}")

        self.tokens.append(Token(TokenType.STEP_OUTCOME, (step_id, property_name), start))
        return True

    def _try_keyword_or_operator(self) -> bool:
        """Try to parse keywords and operators."""
        remaining = self.expression[self.position :].lower()

        for keyword, token_type in [
            ("not in", TokenType.NOT_IN),
            ("always", TokenType.KEYWORD),
            ("never", TokenType.KEYWORD),
            ("manual", TokenType.KEYWORD),
            ("true", TokenType.KEYWORD),
            ("false", TokenType.KEYWORD),
            ("not", TokenType.NOT),
            ("and", TokenType.AND),
            ("or", TokenType.OR),
            ("in", TokenType.IN),
            ("==", TokenType.EQ),
            ("!=", TokenType.NEQ),
        ]:
            if remaining.startswith(keyword):
                actual_keyword = self.expression[self.position : self.position + len(keyword)]
                is_word = keyword.isalpha()
                end_pos = self.position + len(keyword)

                if is_word and end_pos < len(self.expression):
                    next_char = self.expression[end_pos]
                    if next_char.isalnum() or next_char == "_":
                        continue

                self.tokens.append(Token(token_type, actual_keyword.lower(), self.position))
                self.position += len(keyword)
                return True

        return False

    def _try_parentheses(self) -> bool:
        """Try to parse parentheses."""
        if self.position >= len(self.expression):
            return False

        char = self.expression[self.position]
        if char == "(":
            self.tokens.append(Token(TokenType.LPAREN, "(", self.position))
            self.position += 1
            return True
        elif char == ")":
            self.tokens.append(Token(TokenType.RPAREN, ")", self.position))
            self.position += 1
            return True

        return False

    def _try_brackets(self) -> bool:
        """Try to parse square brackets (used in list parsing)."""
        if self.position >= len(self.expression):
            return False

        char = self.expression[self.position]
        if char == "[":
            self.tokens.append(Token(TokenType.LBRACKET, "[", self.position))
            self.position += 1
            return True
        elif char == "]":
            self.tokens.append(Token(TokenType.RBRACKET, "]", self.position))
            self.position += 1
            return True

        return False

    def _try_comma(self) -> bool:
        """Try to parse a comma."""
        if self.position >= len(self.expression) or self.expression[self.position] != ",":
            return False

        self.tokens.append(Token(TokenType.COMMA, ",", self.position))
        self.position += 1
        return True


class Parser:
    """Recursive descent parser for condition expressions."""

    def __init__(
        self, tokens: list[Token], variables: dict[str, Any], step_outcomes: dict[str, Any]
    ):
        """Initialize the parser.

        Args:
            tokens: List of tokens to parse.
            variables: Dictionary of variables for substitution.
            step_outcomes: Dictionary of step outcomes for lookups.
        """
        self.tokens = tokens
        self.variables = variables
        self.step_outcomes = step_outcomes
        self.position = 0
        self.depth = 0
        self.max_depth = 10

    def parse(self) -> bool | None:
        """Parse and evaluate the expression.

        Returns:
            The result of evaluating the expression.

        Raises:
            ConditionEvalError: If parsing or evaluation fails.
        """
        result = self._expr()
        if not self._is_at_end():
            raise ConditionEvalError(
                f"Unexpected token at position {self._current_token().position}"
            )
        return result

    def _expr(self) -> bool | None:
        """Parse an expression (or_expr)."""
        return self._or_expr()

    def _or_expr(self) -> bool | None:
        """Parse an or expression."""
        left = self._and_expr()

        while self._match(TokenType.OR):
            right = self._and_expr()
            if left is None or right is None:
                left = None
            else:
                left = left or right

        return left

    def _and_expr(self) -> bool | None:
        """Parse an and expression."""
        left = self._not_expr()

        while self._match(TokenType.AND):
            right = self._not_expr()
            if left is None or right is None:
                left = None
            else:
                left = left and right

        return left

    def _not_expr(self) -> bool | None:
        """Parse a not expression."""
        if self._match(TokenType.NOT):
            result = self._not_expr()
            if result is None:
                return None
            return not result

        return self._compare()

    def _compare(self) -> bool | None:
        """Parse a comparison expression."""
        left = self._primary()

        if self._match(TokenType.EQ):
            right = self._primary()
            result = self._compare_values(left, right, "==")
            return result
        elif self._match(TokenType.NEQ):
            right = self._primary()
            result = self._compare_values(left, right, "!=")
            return result
        elif self._match(TokenType.IN):
            right = self._primary()
            return self._check_membership(left, right, True)
        elif self._match(TokenType.NOT_IN):
            right = self._primary()
            return self._check_membership(left, right, False)

        if isinstance(left, bool) or left is None:
            return left
        return False

    def _primary(self) -> bool | None | str | int | float | list[Any]:
        """Parse a primary expression."""
        self.depth += 1
        if self.depth > self.max_depth:
            raise ConditionEvalError("Expression nesting exceeds maximum depth of 10")

        try:
            if self._match(TokenType.STRING):
                return self._previous_token().value

            if self._match(TokenType.NUMBER):
                return self._previous_token().value

            if self._match(TokenType.LIST):
                return self._previous_token().value

            if self._match(TokenType.VARIABLE):
                var_name = self._previous_token().value
                value = self.variables.get(var_name)
                return value if value is not None else ""

            if self._match(TokenType.STEP_OUTCOME):
                step_id, property_name = self._previous_token().value
                if step_id in self.step_outcomes:
                    outcome = self.step_outcomes[step_id]
                    if isinstance(outcome, StepOutcome):
                        return getattr(outcome, property_name, "")
                    elif isinstance(outcome, dict):
                        outcome_dict = cast(dict[str, Any], outcome)
                        value = outcome_dict.get(property_name)
                        return value if value is not None else ""
                return ""

            if self._match(TokenType.KEYWORD):
                keyword = self._previous_token().value
                if keyword in ("always", "true"):
                    return True
                elif keyword in ("never", "false"):
                    return False
                elif keyword == "manual":
                    return None

            if self._match(TokenType.LPAREN):
                result = self._expr()
                if not self._match(TokenType.RPAREN):
                    raise ConditionEvalError("Expected ')' after expression")
                return result

            raise ConditionEvalError(f"Unexpected token: {self._current_token().type}")
        finally:
            self.depth -= 1

    def _compare_values(self, left: Any, right: Any, op: str) -> bool:
        """Compare two values.

        Args:
            left: Left operand.
            right: Right operand.
            op: Comparison operator ("==" or "!=").

        Returns:
            Result of the comparison.
        """
        if op == "==":
            return left == right
        elif op == "!=":
            return left != right
        return False

    def _check_membership(self, item: Any, container: Any, should_contain: bool) -> bool:
        """Check if an item is in a container.

        Args:
            item: The item to check.
            container: The container to search in.
            should_contain: True to check 'in', False to check 'not in'.

        Returns:
            Result of the membership test.
        """
        if not isinstance(container, list):
            return False if should_contain else True

        is_member = item in container
        return is_member if should_contain else not is_member

    def _match(self, *types: TokenType) -> bool:
        """Check if current token matches any of the given types."""
        for token_type in types:
            if self._check(token_type):
                self._advance()
                return True
        return False

    def _check(self, token_type: TokenType) -> bool:
        """Check if current token is of the given type."""
        if self._is_at_end():
            return False
        return self._current_token().type == token_type

    def _advance(self) -> Token:
        """Move to the next token."""
        if not self._is_at_end():
            self.position += 1
        return self._previous_token()

    def _is_at_end(self) -> bool:
        """Check if we're at the end of tokens."""
        return self._current_token().type == TokenType.EOF

    def _current_token(self) -> Token:
        """Get the current token."""
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return self.tokens[-1]

    def _previous_token(self) -> Token:
        """Get the previous token."""
        return self.tokens[self.position - 1]


class ConditionEvaluator:
    """Evaluates conditional expressions safely using recursive descent parsing.

    This evaluator supports boolean logic and variable substitution with
    a safe, restricted parsing approach.
    """

    def evaluate(
        self, expression: str, variables: dict[str, Any], step_outcomes: dict[str, Any]
    ) -> bool | None:
        """Evaluate a conditional expression.

        Args:
            expression: The conditional expression to evaluate.
            variables: Dictionary of variables available in the expression.
            step_outcomes: Dictionary mapping step IDs to StepOutcome objects.

        Returns:
            The boolean result of the expression, or None if evaluation fails.

        Raises:
            ConditionEvalError: If the expression is invalid or evaluation fails.
        """
        if not expression or not expression.strip():
            raise ConditionEvalError("Expression cannot be empty")

        tokenizer = Tokenizer(expression)
        tokens = tokenizer.tokenize()

        parser = Parser(tokens, variables, step_outcomes)
        return parser.parse()
