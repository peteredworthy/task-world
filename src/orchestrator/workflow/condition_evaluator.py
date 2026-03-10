"""Safe expression parser and evaluator using recursive descent.

This module provides a safe way to evaluate conditional expressions
without risky built-in functions.
"""

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
        if not expression:
            raise ConditionEvalError("Expression must be a non-empty string")

        # Normalize expression
        expr_trimmed = expression.strip().lower()

        # Handle literal boolean values
        if expr_trimmed == "true":
            return True
        if expr_trimmed == "false":
            return False

        # Handle step outcome checks: steps.<ID>.<field>
        if expr_trimmed.startswith("steps."):
            return self._evaluate_step_outcome(expr_trimmed, step_outcomes)

        # Handle variable checks: context.<field> or other variables
        if "." in expr_trimmed or "==" in expr_trimmed or "!=" in expr_trimmed:
            return self._evaluate_variable_expression(expression, variables)

        # If we can't evaluate, return None (for manual gates)
        return None

    def _evaluate_step_outcome(self, expression: str, step_outcomes: dict[str, Any]) -> bool:
        """Evaluate step outcome expressions like 'steps.S1.completed'."""
        parts = expression.split(".")
        if len(parts) < 3:
            raise ConditionEvalError(f"Invalid step outcome expression: {expression}")

        step_id = parts[1]
        field = ".".join(parts[2:])  # Handle nested fields

        if step_id not in step_outcomes:
            # Step not yet completed/skipped - condition is false
            return False

        outcome = step_outcomes[step_id]
        if not isinstance(outcome, StepOutcome):
            raise ConditionEvalError(f"Invalid step outcome for {step_id}")

        # Support common outcome fields
        if field == "completed":
            return outcome.completed
        elif field == "skipped":
            return outcome.skipped
        elif field == "has_failures":
            return outcome.has_failures
        elif field == "all_passed":
            return outcome.all_passed
        elif field == "any_completed":
            return outcome.any_completed
        else:
            raise ConditionEvalError(f"Unknown step outcome field: {field}")

    def _evaluate_variable_expression(self, expression: str, variables: dict[str, Any]) -> bool:
        """Evaluate simple variable expressions with == and != operators."""
        # Handle equality comparisons
        if "==" in expression:
            parts = expression.split("==")
            if len(parts) != 2:
                raise ConditionEvalError(f"Invalid comparison expression: {expression}")
            left = parts[0].strip()
            right = parts[1].strip()
            left_val = self._get_variable_value(left, variables)
            right_val = self._parse_literal_value(right)
            return left_val == right_val

        # Handle inequality comparisons
        if "!=" in expression:
            parts = expression.split("!=")
            if len(parts) != 2:
                raise ConditionEvalError(f"Invalid comparison expression: {expression}")
            left = parts[0].strip()
            right = parts[1].strip()
            left_val = self._get_variable_value(left, variables)
            right_val = self._parse_literal_value(right)
            return left_val != right_val

        # If no operator, try to get variable as boolean
        return bool(self._get_variable_value(expression, variables))

    def _get_variable_value(self, var_path: str, variables: dict[str, Any]) -> Any:
        """Get a value from variables using dot notation (e.g., 'context.env')."""
        parts = var_path.strip().split(".")
        if not parts:
            raise ConditionEvalError(f"Invalid variable path: {var_path}")

        value: Any = variables.get(parts[0])
        for part in parts[1:]:
            if not isinstance(value, dict):
                raise ConditionEvalError(f"Cannot access {part} on {type(value).__name__}")
            value = cast(dict[str, Any], value).get(part)
            if value is None:
                break
        return value

    def _parse_literal_value(self, value_str: str) -> Any:
        """Parse a literal value (string, number, boolean)."""
        value_str = value_str.strip()

        # Boolean values
        if value_str.lower() == "true":
            return True
        if value_str.lower() == "false":
            return False

        # Numeric values
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            pass

        # String values (remove quotes if present)
        if (value_str.startswith("'") and value_str.endswith("'")) or (
            value_str.startswith('"') and value_str.endswith('"')
        ):
            return value_str[1:-1]

        # Return as-is if not recognized
        return value_str
