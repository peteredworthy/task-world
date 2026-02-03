"""Custom exceptions for routine loading."""


class RoutineError(Exception):
    """Base class for routine errors."""


class RoutineNotFoundError(RoutineError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Routine not found: {path}")


class RoutineParseError(RoutineError):
    def __init__(self, path: str, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Failed to parse routine {path}: {detail}")


class RoutineValidationError(RoutineError):
    def __init__(self, path: str, errors: list[str]) -> None:
        self.path = path
        self.errors = errors
        super().__init__(f"Routine validation failed {path}: {errors}")
