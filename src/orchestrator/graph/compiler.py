"""Pure routine-to-graph compiler.

The compiler maps routine YAML models to initial graph facts without loading
files, touching a database, or consulting runtime state. Steps are represented
as grouping metadata on task regions rather than nodes; this keeps the
single-task graph minimal while preserving step order through dependency edges
between adjacent step regions.

Auto-verify compiles to one check node per item so each command has independent
state, retry, and future appeal semantics. Fan-out input glob expansion is
runtime work because the pure compiler does not inspect files; fan-out therefore
compiles to one reader template plus a distinct synthesis/join template node
that runtime expansion can multiply before the worker consumes joined inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from orchestrator.config.models import (
    AutoVerifyItemConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.graph.commands import Clock, IdGenerator
from orchestrator.graph.models import Actor, ActorKind, EventEnvelope


def compile_routine(
    routine: RoutineConfig,
    clock: Clock,
    id_gen: IdGenerator,
    *,
    run_id: str,
    source_path: str | None = None,
    source_ref: str | None = None,
) -> list[EventEnvelope]:
    """Compile a validated routine config into ordered initial graph events.

    The returned events are append-ready graph facts with placeholder
    positions. The effectful store assigns durable run-local positions when the
    events are seeded.
    """
    builder = _Compiler(routine, clock, id_gen, run_id, source_path, source_ref)
    return builder.compile()


class _Compiler:
    def __init__(
        self,
        routine: RoutineConfig,
        clock: Clock,
        id_gen: IdGenerator,
        run_id: str,
        source_path: str | None,
        source_ref: str | None,
    ) -> None:
        self._routine = routine
        self._clock = clock
        self._id_gen = id_gen
        self._run_id = run_id
        self._source_path = source_path
        self._source_ref = source_ref
        self._events: list[EventEnvelope] = []
        self._stem_counts = _task_stem_counts(routine)

    def compile(self) -> list[EventEnvelope]:
        self._create_root()
        self._create_routine_snapshot()

        prior_step_terminals: list[str] = []
        for step_index, step in enumerate(self._routine.steps):
            step_entries: list[str] = []
            step_terminals: list[str] = []

            gate_id = self._create_step_gate(step, step_index)
            if gate_id is not None:
                step_entries.append(gate_id)

            for task_index, task in enumerate(step.tasks):
                compiled = self._compile_task(step, task, step_index, task_index, gate_id)
                step_entries.extend(compiled.entry_node_ids)
                step_terminals.extend(compiled.terminal_node_ids)

            for upstream_node_id in prior_step_terminals:
                for entry_node_id in step_entries:
                    self._edge(
                        upstream_node_id,
                        "completion",
                        entry_node_id,
                        "prior_step_completion",
                        purpose="step_order",
                        dependency_type="state_dependency",
                    )
            prior_step_terminals = step_terminals or step_entries

        return self._events

    def _create_root(self) -> None:
        self._node(
            {
                "node_id": "root",
                "kind": "root",
                "state": "completed",
                "role": "run_root",
                "outputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "output",
                        "schema": "RoutineSnapshot",
                        "record_layers": ["graph_record"],
                    }
                ],
                "routine": {
                    "id": self._routine.id,
                    "name": self._routine.name,
                },
            }
        )

    def _create_routine_snapshot(self) -> None:
        self._node(
            {
                "node_id": _ROUTINE_SNAPSHOT_NODE_ID,
                "kind": "artifact",
                "state": "completed",
                "role": "routine_snapshot",
                "outputs": [
                    {
                        "port": "snapshot",
                        "direction": "output",
                        "schema": "RoutineSnapshot",
                        "record_layers": ["graph_record"],
                    }
                ],
                "snapshot": {
                    "routine_id": self._routine.id,
                    "name": self._routine.name,
                    "description": self._routine.description,
                    "content_hash": _routine_content_hash(self._routine),
                    "source_path": self._source_path,
                    "source_ref": self._source_ref,
                    "step_count": len(self._routine.steps),
                    "task_count": sum(len(step.tasks) for step in self._routine.steps),
                    "builder_agent": self._routine.builder_agent,
                    "verifier_agent": self._routine.verifier_agent,
                },
            }
        )

    def _create_step_gate(self, step: StepConfig, step_index: int) -> str | None:
        if step.gate is None:
            return None

        base_gate_id = f"gate-{_slug(step.id)}"
        duplicate_step_ids = (
            sum(1 for candidate in self._routine.steps if candidate.id == step.id) > 1
        )
        gate_id = f"{base_gate_id}-{step_index + 1:02d}" if duplicate_step_ids else base_gate_id
        first_task_region = (
            _task_region_id(step, step.tasks[0]) if step.tasks else f"step:{step.id}"
        )
        self._node(
            {
                "node_id": gate_id,
                "kind": "gate",
                "state": "planned",
                "role": "step_gate",
                "task_region_id": first_task_region,
                "step_id": step.id,
                "step_index": step_index,
                "gate": step.gate.model_dump(mode="json"),
                "inputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "input",
                        "schema": "RoutineSnapshot",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "approval",
                        "direction": "output",
                        "schema": "ApprovalDecision",
                        "record_layers": ["graph_record"],
                    }
                ],
            }
        )
        edge_id = self._edge(
            _ROUTINE_SNAPSHOT_NODE_ID,
            "snapshot",
            gate_id,
            "routine_snapshot",
            purpose="routine_snapshot",
        )
        self._bind(edge_id, gate_id, "routine_snapshot", [_ROUTINE_SNAPSHOT_NODE_ID])
        return gate_id

    def _compile_task(
        self,
        step: StepConfig,
        task: TaskConfig,
        step_index: int,
        task_index: int,
        gate_id: str | None,
    ) -> "_CompiledTask":
        task_region_id = _task_region_id(step, task)
        stem = self._task_stem(step, task, step_index, task_index)
        worker_id = f"worker-{stem}"
        candidate_id = f"candidate-{stem}-1"
        entry_node_ids: list[str] = []

        if task.fan_out is None:
            entry_node_id = worker_id
            join_id = None
        else:
            entry_node_id = f"fanout-reader-{stem}"
            join_id = f"fanout-join-{stem}"
            self._create_fanout_reader(entry_node_id, task, task_region_id, step_index, task_index)
            self._create_fanout_join(join_id, task, task_region_id, step_index, task_index)
            entry_node_ids.append(entry_node_id)

        worker_role = "builder"
        self._create_worker(
            worker_id,
            task,
            task_region_id,
            candidate_id,
            step,
            step_index,
            task_index,
            worker_role,
        )
        if task.fan_out is None:
            entry_node_ids.append(worker_id)
        else:
            self._edge(
                entry_node_id,
                "reader_output",
                str(join_id),
                "reader_outputs",
                purpose="fan_out_join",
            )
            self._edge(
                str(join_id),
                "fan_out_inputs",
                worker_id,
                "fan_out_inputs",
                purpose="fan_out_worker_input",
            )

        if gate_id is not None:
            for entry_id in entry_node_ids:
                edge_id = self._edge(gate_id, "approval", entry_id, "approval", purpose="gate")
                self._bind(edge_id, entry_id, "approval", [gate_id])

        self._bind_routine_snapshot(entry_node_id)
        self._compile_context_sources(task, entry_node_id, stem)

        requirement_node_ids = self._compile_requirements(task, worker_id, stem)
        verifier_id = self._create_verifier_if_needed(
            task, worker_id, task_region_id, candidate_id, stem
        )
        if verifier_id is not None:
            for requirement_node_id in requirement_node_ids:
                self._bind_requirement(requirement_node_id, verifier_id)

        check_ids = self._compile_checks(
            task.auto_verify.items,
            task.auto_verify.tail_lines,
            worker_id,
            task_region_id,
            candidate_id,
            stem,
            "auto_verify",
        )
        if task.fan_out is not None and task.fan_out.auto_verify is not None:
            check_ids.extend(
                self._compile_checks(
                    task.fan_out.auto_verify.items,
                    task.fan_out.auto_verify.tail_lines,
                    worker_id,
                    task_region_id,
                    candidate_id,
                    stem,
                    "fan_out_auto_verify",
                )
            )

        terminal_node_ids = check_ids.copy()
        if verifier_id is not None:
            terminal_node_ids.append(verifier_id)
        if not terminal_node_ids:
            terminal_node_ids.append(worker_id)

        # Every executable node needs a base snapshot identity to be leasable —
        # the scheduler defers nodes without one rather than fabricating it.
        for executable_id in {worker_id, verifier_id, *check_ids} - {entry_node_id, None}:
            self._bind_routine_snapshot(str(executable_id))
        return _CompiledTask(entry_node_ids=entry_node_ids, terminal_node_ids=terminal_node_ids)

    def _create_worker(
        self,
        worker_id: str,
        task: TaskConfig,
        task_region_id: str,
        candidate_id: str,
        step: StepConfig,
        step_index: int,
        task_index: int,
        role: str,
    ) -> None:
        self._node(
            {
                "node_id": worker_id,
                "kind": "worker",
                "state": "planned",
                "role": role,
                "task_region_id": task_region_id,
                "attempt_number": 1,
                "candidate_id": candidate_id,
                "execution_id": f"exec-{worker_id}-1",
                "step_id": step.id,
                "step_index": step_index,
                "task_id": task.id,
                "task_index": task_index,
                "title": task.title,
                "task_context": task.task_context,
                "work_mode": task.work_mode,
                "complexity": task.complexity.value,
                "profile": task.profile.value if task.profile is not None else None,
                "builder_agent": task.builder_agent
                or step.builder_agent
                or self._routine.builder_agent,
                "available_tools": task.available_tools or step.available_tools,
                "mcp_servers": [
                    server.model_dump(mode="json")
                    for server in (task.mcp_servers or step.mcp_servers or [])
                ],
                "authority": {
                    "allowed_actions": [
                        "submit_records",
                        "request_clarification",
                        "raise_appeal",
                    ],
                    "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["."]}],
                },
                "inputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "input",
                        "schema": "RoutineSnapshot",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "candidate",
                        "direction": "output",
                        "schema": "ImplementationCandidate",
                        "record_layers": ["output", "file_state"],
                    },
                    {
                        "port": "completion",
                        "direction": "output",
                        "schema": "NodeCompletion",
                        "record_layers": ["graph_record"],
                    },
                ],
                "artifacts": [artifact.model_dump(mode="json") for artifact in task.artifacts],
                "fan_out": task.fan_out.model_dump(mode="json")
                if task.fan_out is not None
                else None,
            }
        )

    def _create_fanout_reader(
        self,
        reader_id: str,
        task: TaskConfig,
        task_region_id: str,
        step_index: int,
        task_index: int,
    ) -> None:
        fan_out = task.fan_out
        if fan_out is None:
            return
        self._node(
            {
                "node_id": reader_id,
                "kind": "planner",
                "state": "planned",
                "role": "fan_out_reader",
                "task_region_id": task_region_id,
                "attempt_number": 1,
                "candidate_id": f"fanout-inputs-{_slug(task_region_id)}",
                "execution_id": f"exec-{reader_id}-1",
                "step_index": step_index,
                "task_index": task_index,
                "fan_out": fan_out.model_dump(mode="json"),
                "authority": {
                    "allowed_actions": ["submit_records", "request_clarification"],
                    "resource_claims": [
                        {"mode": "read", "scope": "repo", "paths": [fan_out.input_glob]}
                    ],
                },
                "inputs": [
                    {
                        "port": "routine_snapshot",
                        "direction": "input",
                        "schema": "RoutineSnapshot",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "reader_output",
                        "direction": "output",
                        "schema": "FanOutInputs",
                        "record_layers": ["output"],
                    }
                ],
            }
        )

    def _create_fanout_join(
        self,
        join_id: str,
        task: TaskConfig,
        task_region_id: str,
        step_index: int,
        task_index: int,
    ) -> None:
        fan_out = task.fan_out
        if fan_out is None:
            return
        self._node(
            {
                "node_id": join_id,
                "kind": "planner",
                "state": "planned",
                "role": "fan_out_join",
                "task_region_id": task_region_id,
                "attempt_number": 1,
                "candidate_id": f"fanout-joined-{_slug(task_region_id)}",
                "execution_id": f"exec-{join_id}-1",
                "step_index": step_index,
                "task_index": task_index,
                "fan_out": fan_out.model_dump(mode="json"),
                "authority": {
                    "allowed_actions": ["submit_records", "request_clarification"],
                    "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["."]}],
                },
                "inputs": [
                    {
                        "port": "reader_outputs",
                        "direction": "input",
                        "schema": "FanOutInputs",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "fan_out_inputs",
                        "direction": "output",
                        "schema": "FanOutJoinedInputs",
                        "record_layers": ["output"],
                    }
                ],
            }
        )

    def _compile_requirements(
        self,
        task: TaskConfig,
        worker_id: str,
        stem: str,
    ) -> list[str]:
        requirement_node_ids: list[str] = []
        for requirement in task.requirements:
            requirement_id = f"requirement-{stem}-{_slug(requirement.id)}"
            self._node(
                {
                    "node_id": requirement_id,
                    "kind": "requirement",
                    "state": "completed",
                    "role": "requirement",
                    "requirement": requirement.model_dump(mode="json"),
                    "outputs": [
                        {
                            "port": "requirement",
                            "direction": "output",
                            "schema": "Requirement",
                            "record_layers": ["graph_record"],
                        }
                    ],
                }
            )
            self._bind_requirement(requirement_id, worker_id)
            requirement_node_ids.append(requirement_id)
        return requirement_node_ids

    def _bind_requirement(self, requirement_node_id: str, target_node_id: str) -> None:
        port = f"requirement_{_slug(requirement_node_id)}"
        edge_id = self._edge(
            requirement_node_id,
            "requirement",
            target_node_id,
            port,
            purpose="requirement",
        )
        self._bind(edge_id, target_node_id, port, [requirement_node_id])

    def _create_verifier_if_needed(
        self,
        task: TaskConfig,
        worker_id: str,
        task_region_id: str,
        candidate_id: str,
        stem: str,
    ) -> str | None:
        if not task.verifier.rubric:
            return None

        verifier_id = f"verifier-{stem}"
        self._node(
            {
                "node_id": verifier_id,
                "kind": "verifier",
                "state": "planned",
                "role": "verifier",
                "task_region_id": task_region_id,
                "attempt_number": 1,
                "candidate_id": candidate_id,
                "execution_id": f"exec-{verifier_id}-1",
                "verifier_agent": task.verifier_agent or self._routine.verifier_agent,
                "rubric": [item.model_dump(mode="json") for item in task.verifier.rubric],
                "submission_template": task.verifier.submission_template.model_dump(mode="json"),
                "authority": {
                    "allowed_actions": ["submit_records", "raise_appeal"],
                    "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["."]}],
                },
                "inputs": [
                    {
                        "port": "candidate_under_test",
                        "direction": "input",
                        "schema": "ImplementationCandidate",
                        "required": True,
                    }
                ],
                "outputs": [
                    {
                        "port": "verification_report",
                        "direction": "output",
                        "schema": "VerificationReport",
                        "record_layers": ["output", "graph_record"],
                    }
                ],
            }
        )
        self._edge(
            worker_id,
            "candidate",
            verifier_id,
            "candidate_under_test",
            purpose="candidate_verification",
        )
        # §20.4: downstream consumers bind to the accepted file-state record.
        # Optional (required=False) in v1: binding happens when the boundary
        # produces a record; pure-kernel paths without a boundary still verify.
        self._edge(
            worker_id,
            "file_state",
            verifier_id,
            "file_state",
            purpose="file_state_consumption",
            required=False,
        )
        return verifier_id

    def _compile_checks(
        self,
        items: list[AutoVerifyItemConfig],
        tail_lines: int,
        worker_id: str,
        task_region_id: str,
        candidate_id: str,
        stem: str,
        source: str,
    ) -> list[str]:
        check_ids: list[str] = []
        for index, item in enumerate(items):
            check_id = f"check-{stem}-{_slug(source)}-{_slug(item.id)}"
            self._node(
                {
                    "node_id": check_id,
                    "kind": "check",
                    "state": "planned",
                    "role": source,
                    "task_region_id": task_region_id,
                    "attempt_number": 1,
                    "candidate_id": candidate_id,
                    "execution_id": f"exec-{check_id}-1",
                    "check_index": index,
                    "command_definition": {
                        "id": item.id,
                        "cmd": item.cmd,
                        "must": item.must,
                        "tail_lines": tail_lines,
                        "source": source,
                    },
                    "authority": {
                        "allowed_actions": ["submit_records"],
                        "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["."]}],
                    },
                    "inputs": [
                        {
                            "port": "candidate_under_test",
                            "direction": "input",
                            "schema": "ImplementationCandidate",
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "port": "check_result",
                            "direction": "output",
                            "schema": "CheckResult",
                            "record_layers": ["output", "graph_record"],
                        }
                    ],
                }
            )
            self._edge(
                worker_id,
                "candidate",
                check_id,
                "candidate_under_test",
                purpose=source,
            )
            self._edge(
                worker_id,
                "file_state",
                check_id,
                "file_state",
                purpose="file_state_consumption",
                required=False,
            )
            check_ids.append(check_id)
        return check_ids

    def _compile_context_sources(self, task: TaskConfig, entry_node_id: str, stem: str) -> None:
        for index, source in enumerate(task.context_from):
            context_node_id = f"context-{stem}-{index}-{_slug(source.as_name or source.artifact)}"
            self._node(
                {
                    "node_id": context_node_id,
                    "kind": "artifact",
                    "state": "completed",
                    "role": "context_source",
                    "context_source": source.model_dump(mode="json", by_alias=True),
                    "outputs": [
                        {
                            "port": "artifact",
                            "direction": "output",
                            "schema": "ContextArtifact",
                            "record_layers": ["graph_record"],
                        }
                    ],
                }
            )
            port = f"context_{index}"
            edge_id = self._edge(
                context_node_id,
                "artifact",
                entry_node_id,
                port,
                purpose="context_dependency",
                required=source.required,
            )
            if source.required:
                self._bind(edge_id, entry_node_id, port, [context_node_id])

    def _bind_routine_snapshot(self, node_id: str) -> None:
        edge_id = self._edge(
            _ROUTINE_SNAPSHOT_NODE_ID,
            "snapshot",
            node_id,
            "routine_snapshot",
            purpose="routine_snapshot",
        )
        self._bind(edge_id, node_id, "routine_snapshot", [_ROUTINE_SNAPSHOT_NODE_ID])

    def _node(self, payload: dict[str, Any]) -> None:
        payload.setdefault("run_id", self._run_id)
        self._event("node_created", payload)

    def _edge(
        self,
        from_node_id: str,
        from_port: str,
        to_node_id: str,
        to_port: str,
        *,
        purpose: str,
        required: bool = True,
        dependency_type: str = "input_binding",
    ) -> str:
        edge_id = (
            f"edge-{_slug(from_node_id)}-{_slug(from_port)}-to-{_slug(to_node_id)}-{_slug(to_port)}"
        )
        self._event(
            "edge_created",
            {
                "edge_id": edge_id,
                "from_node_id": from_node_id,
                "from_port": from_port,
                "to_node_id": to_node_id,
                "to_port": to_port,
                "required": required,
                "purpose": purpose,
                "dependency_type": dependency_type,
            },
        )
        return edge_id

    def _bind(
        self,
        edge_id: str,
        to_node_id: str,
        to_port: str,
        record_ids: list[str],
    ) -> None:
        self._event(
            "input_bound",
            {
                "edge_id": edge_id,
                "to_node_id": to_node_id,
                "to_port": to_port,
                "record_ids": record_ids,
                "bound_at_position": 0,
            },
        )

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._events.append(
            EventEnvelope(
                event_id=self._id_gen.next_id("event"),
                run_id=self._run_id,
                position=-1,
                event_type=event_type,
                schema_version=1,
                actor=Actor(kind=ActorKind.CONTROLLER),
                causation_id="compile_routine",
                correlation_id=_correlation_id(payload),
                timestamp=self._clock.now(),
                payload=payload,
            )
        )

    def _task_stem(
        self,
        step: StepConfig,
        task: TaskConfig,
        step_index: int,
        task_index: int,
    ) -> str:
        base = _task_stem(step, task)
        if self._stem_counts.get(base, 0) <= 1:
            return base
        return f"{step_index + 1:02d}-{base}-{task_index + 1:02d}"


class _CompiledTask:
    def __init__(self, entry_node_ids: list[str], terminal_node_ids: list[str]) -> None:
        self.entry_node_ids = entry_node_ids
        self.terminal_node_ids = terminal_node_ids


_ROUTINE_SNAPSHOT_NODE_ID = "routine-snapshot"
_SLUG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _task_region_id(step: StepConfig, task: TaskConfig) -> str:
    return f"{step.id}/{task.id}"


def _task_stem(step: StepConfig, task: TaskConfig) -> str:
    return f"{_slug(step.id)}-{_slug(task.id)}"


def _task_stem_counts(routine: RoutineConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in routine.steps:
        for task in step.tasks:
            stem = _task_stem(step, task)
            counts[stem] = counts.get(stem, 0) + 1
    return counts


def _routine_content_hash(routine: RoutineConfig) -> str:
    canonical = json.dumps(
        routine.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    stripped = _SLUG_RE.sub("-", value.strip()).strip("-._").lower()
    return stripped or "item"


def _correlation_id(payload: dict[str, Any]) -> str | None:
    node_id = payload.get("node_id")
    if isinstance(node_id, str):
        return node_id
    edge_id = payload.get("edge_id")
    if isinstance(edge_id, str):
        return edge_id
    return None
