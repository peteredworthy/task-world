"""State-related error types."""


class StateError(Exception):
    """Base class for state errors."""


class RunNotFoundError(StateError):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Run not found: {run_id}")


class StepNotFoundError(StateError):
    def __init__(self, step_id: str) -> None:
        self.step_id = step_id
        super().__init__(f"Step not found: {step_id}")


class TaskNotFoundError(StateError):
    def __init__(self, run_id: str, task_id: str) -> None:
        self.run_id = run_id
        self.task_id = task_id
        super().__init__(f"Task {task_id} not found in run {run_id}")


class ChecklistItemNotFoundError(StateError):
    def __init__(self, run_id: str, task_id: str, req_id: str) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.req_id = req_id
        super().__init__(f"Requirement {req_id} not found in task {task_id} of run {run_id}")


class MissingRequiredInputError(StateError):
    def __init__(self, input_name: str) -> None:
        self.input_name = input_name
        super().__init__(f"Missing required input: {input_name}")
