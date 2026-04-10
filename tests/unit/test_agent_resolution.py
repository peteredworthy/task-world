"""Unit tests for agent name resolution — pure function, no DB needed."""

from orchestrator.runners import resolve_agent_name


class TestResolveAgentName:
    def test_task_agent_wins_over_all(self) -> None:
        assert (
            resolve_agent_name("builder", "TaskAgent", "StepAgent", "RoutineAgent") == "TaskAgent"
        )

    def test_step_agent_wins_over_routine_and_default(self) -> None:
        assert resolve_agent_name("builder", None, "StepAgent", "RoutineAgent") == "StepAgent"

    def test_routine_agent_wins_over_default(self) -> None:
        assert resolve_agent_name("builder", None, None, "RoutineAgent") == "RoutineAgent"

    def test_system_default_builder_when_all_none(self) -> None:
        assert resolve_agent_name("builder", None, None, None) == "Builder"

    def test_system_default_verifier_when_all_none(self) -> None:
        assert resolve_agent_name("verifier", None, None, None) == "Verifier"

    def test_system_default_planner_when_all_none(self) -> None:
        assert resolve_agent_name("planner", None, None, None) == "Planner"

    def test_task_none_step_none_routine_set(self) -> None:
        assert resolve_agent_name("verifier", None, None, "CustomVerifier") == "CustomVerifier"

    def test_task_set_step_none_routine_none(self) -> None:
        assert resolve_agent_name("planner", "MyPlanner", None, None) == "MyPlanner"

    def test_step_set_routine_none(self) -> None:
        assert resolve_agent_name("planner", None, "StepPlanner", None) == "StepPlanner"

    def test_task_overrides_step(self) -> None:
        assert resolve_agent_name("verifier", "TaskV", "StepV", None) == "TaskV"

    def test_task_overrides_routine(self) -> None:
        assert resolve_agent_name("verifier", "TaskV", None, "RoutineV") == "TaskV"
