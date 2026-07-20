"""Runner usage metadata is retained at provider and execution boundaries."""

from __future__ import annotations

import os
from typing import Any

import pytest

from orchestrator.runners import (
    ClaudeStreamParser,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    MockAgent,
    MockBehavior,
    OpenHandsAgent,
    DockerOpenHandsAgent,
    extract_metrics_and_usage,
    extract_turn_finish_reasons,
)
from orchestrator.runners import PhaseHandler
from orchestrator.graph_runtime import GraphDispatchContext, GraphDispatchExecutor
from orchestrator.state import ActionLog, SubAgentLog


class _MonotonicSequence:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class _LatencyAgent:
    def __init__(self) -> None:
        self.result: ExecutionResult | None = None

    async def execute(self, *args: Any, **kwargs: Any) -> ExecutionResult:
        self.result = ExecutionResult(success=True, metrics=ExecutionMetrics(duration_ms=999))
        return self.result


class _GraphLatencyExecutor(GraphDispatchExecutor):
    def __init__(self, monotonic: _MonotonicSequence) -> None:
        self._monotonic = monotonic
        self._on_agent_output = None
        self._on_agent_usage = None
        self.death_reasons: list[str] = []

    async def _acknowledge_start(self, context: GraphDispatchContext) -> None:
        return None

    async def _record_start_heartbeat(self, context: GraphDispatchContext) -> None:
        return None

    async def _submit_callback(self, context: GraphDispatchContext, grades: list[Any]) -> None:
        return None

    async def _agent_died(self, context: GraphDispatchContext, reason: str) -> None:
        self.death_reasons.append(reason)

    def _execution_context(self, context: GraphDispatchContext, **kwargs: Any) -> Any:
        return ExecutionContext(
            run_id=context.run_id,
            task_id=context.node_id,
            working_dir=context.worktree_path,
            prompt="p",
            requirements=[],
        )


@pytest.mark.asyncio
async def test_phase_handler_measures_only_agent_execute_with_injected_monotonic() -> None:
    handler = PhaseHandler(
        attempt_store=object(),
        event_broadcaster=object(),
        monotonic=_MonotonicSequence([4.0, 4.375]),
    )

    result = await handler._execute_agent(_LatencyAgent())

    assert result.metrics.duration_ms == 375


@pytest.mark.asyncio
async def test_graph_dispatch_measures_only_agent_execute_with_injected_monotonic() -> None:
    executor = _GraphLatencyExecutor(_MonotonicSequence([10.0, 10.125]))
    context = GraphDispatchContext(
        run_id="run",
        node_id="node",
        node_kind="worker",
        node_payload={},
        requirements=[],
        worktree_path="/tmp",
        lease_id="lease",
        lease_generation=1,
        execution_id="execution",
        base_snapshot_id="snapshot",
        dispatch_event_id="event",
    )

    agent = _LatencyAgent()
    await executor._run_agent(context, agent)

    assert executor.death_reasons == ["agent exited without submit"]
    assert agent.result is not None
    assert agent.result.metrics.duration_ms == 125


def test_codex_terminal_statuses_map_to_normalized_finish_reasons() -> None:
    assert extract_turn_finish_reasons(
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}}
    ) == ["stop"]
    assert extract_turn_finish_reasons(
        {"method": "turn/completed", "params": {"turn": {"status": "interrupted"}}}
    ) == ["cancelled"]
    assert extract_turn_finish_reasons(
        {"method": "turn/completed", "params": {"turn": {"status": "systemError"}}}
    ) == ["error"]
    assert extract_turn_finish_reasons(
        {"method": "turn/completed", "params": {"turn": {"status": "failed"}}}
    ) == ["error"]


def test_codex_reasoning_is_captured_once_in_usage_fact() -> None:
    result = ExecutionResult(
        success=True,
        metrics=ExecutionMetrics(gen_ai_usage_output_tokens=120),
        gen_ai_usage_reasoning_output_tokens=20,
        gen_ai_response_finish_reasons=["stop"],
    )

    _metrics, usage = extract_metrics_and_usage(result)

    assert len(usage) == 1
    assert usage[0].gen_ai_usage_output_tokens == 120
    assert usage[0].gen_ai_usage_reasoning_output_tokens == 20
    assert list(usage[0].gen_ai_response_finish_reasons) == ["stop"]


def test_usage_facts_replicate_execution_latency_to_parent_and_subagents() -> None:
    result = ExecutionResult(
        success=True,
        metrics=ExecutionMetrics(duration_ms=321),
        action_log=ActionLog(
            agent_model="parent",
            gen_ai_usage_input_tokens=10,
            sub_agents=[
                SubAgentLog(model="child-a", gen_ai_usage_input_tokens=20),
                SubAgentLog(model="child-b", gen_ai_usage_output_tokens=30),
            ],
        ),
    )

    _metrics, usage = extract_metrics_and_usage(result)

    assert [item.model for item in usage] == ["parent", "child-a", "child-b"]
    assert [item.latency_ms for item in usage] == [321, 321, 321]


def test_usage_facts_replicate_latency_when_only_subagents_have_usage() -> None:
    result = ExecutionResult(
        success=True,
        metrics=ExecutionMetrics(duration_ms=654),
        action_log=ActionLog(
            sub_agents=[
                SubAgentLog(model="child-a", gen_ai_usage_input_tokens=20),
                SubAgentLog(model="child-b", gen_ai_usage_output_tokens=30),
            ]
        ),
    )

    _metrics, usage = extract_metrics_and_usage(result)

    assert [item.model for item in usage] == ["child-a", "child-b"]
    assert [item.latency_ms for item in usage] == [654, 654]


def test_claude_result_stop_reason_is_preserved() -> None:
    parser = ClaudeStreamParser()
    parser.parse_line(
        '{"type":"result","subtype":"success","stop_reason":"end_turn","result":"done"}'
    )

    assert parser.finish_reasons == ["end_turn"]


def test_mock_agent_passes_usage_metadata_through() -> None:
    behavior = MockBehavior(
        gen_ai_usage_reasoning_output_tokens=13,
        gen_ai_response_finish_reasons=["fixture_stop"],
    )
    agent = MockAgent(behavior)

    assert agent._behavior.gen_ai_usage_reasoning_output_tokens == 13
    assert agent._behavior.gen_ai_response_finish_reasons == ["fixture_stop"]


def test_execution_result_defaults_to_empty_provider_metadata() -> None:
    result = ExecutionResult(success=True)

    assert result.gen_ai_usage_reasoning_output_tokens == 0
    assert result.gen_ai_response_finish_reasons == []


@pytest.mark.asyncio
async def test_mock_agent_returns_usage_metadata() -> None:
    agent = MockAgent(
        MockBehavior(
            should_submit=False,
            gen_ai_usage_reasoning_output_tokens=7,
            gen_ai_response_finish_reasons=["mock_complete"],
        )
    )

    async def checklist(_id: str, _status: Any, _note: str | None) -> None:
        return None

    async def submit() -> None:
        return None

    result = await agent.execute(
        ExecutionContext(
            run_id="run", task_id="task", working_dir="/tmp", prompt="p", requirements=[]
        ),
        checklist,
        submit,
    )

    assert result.gen_ai_usage_reasoning_output_tokens == 7
    assert result.gen_ai_response_finish_reasons == ["mock_complete"]


async def _noop_checklist(_id: str, _status: Any, _note: str | None) -> None:
    return None


async def _noop_submit() -> None:
    return None


_OPENHANDS_LOCAL_URL = os.getenv("OPENHANDS_TEST_LOCAL_BASE_URL")


@pytest.mark.skipif(
    not _OPENHANDS_LOCAL_URL,
    reason="requires an explicitly configured local OpenAI-compatible OpenHands test runtime",
)
@pytest.mark.asyncio
async def test_openhands_local_execute_returns_empty_finish_reasons_without_external_provider() -> (
    None
):
    agent = OpenHandsAgent(
        api_key="",
        llm_config={"base_url": _OPENHANDS_LOCAL_URL},
        max_iterations=1,
    )
    result = await agent.execute(
        ExecutionContext(
            run_id="run", task_id="task", working_dir="/tmp", prompt="Stop.", requirements=[]
        ),
        _noop_checklist,
        _noop_submit,
    )

    assert result.gen_ai_response_finish_reasons == []


_OPENHANDS_DOCKER_URL = os.getenv("OPENHANDS_TEST_DOCKER_BASE_URL")
_OPENHANDS_DOCKER_KEY = os.getenv("OPENHANDS_TEST_DOCKER_API_KEY")


@pytest.mark.skipif(
    not (_OPENHANDS_DOCKER_URL and _OPENHANDS_DOCKER_KEY),
    reason="requires an explicitly configured local Docker OpenHands test runtime",
)
@pytest.mark.asyncio
async def test_openhands_docker_execute_returns_empty_finish_reasons_without_external_provider() -> (
    None
):
    agent = DockerOpenHandsAgent(
        api_key=_OPENHANDS_DOCKER_KEY,
        llm_config={"base_url": _OPENHANDS_DOCKER_URL},
        max_iterations=1,
    )
    result = await agent.execute(
        ExecutionContext(
            run_id="run", task_id="task", working_dir="/tmp", prompt="Stop.", requirements=[]
        ),
        _noop_checklist,
        _noop_submit,
    )

    assert result.gen_ai_response_finish_reasons == []
