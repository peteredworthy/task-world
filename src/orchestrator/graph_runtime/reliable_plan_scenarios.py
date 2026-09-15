"""Executable product-path qualification for the reliable-plan incident.

The fixture manifest is descriptive only.  This module is the attesting
runner: every passing result is constructed after the corresponding production
contract has been exercised and its observable facts have been checked.
"""

from __future__ import annotations

import json
from hashlib import sha256
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    EventEnvelope,
    FakeClock,
    PatchCommandContext,
    GraphProjection,
    ReliablePlanContractIdentity,
    ReliablePlanJoinedCaseManifest,
    ReliablePlanJoinedCaseObservation,
    ReliablePlanJoinedCaseQualification,
    ReliablePlanScenarioDefinition,
    ReliablePlanScenarioManifest,
    ReliablePlanQualificationReceipt,
    ReliablePlanScenarioObservation,
    ReliablePlanSkeletonQualification,
    SequentialIdGenerator,
    canonical_decision_v1_joined_case_manifest,
    canonical_reliable_plan_scenario_manifest,
    event_factory,
    leases_view,
    qualification_from_accepted_records,
    reliable_plan_manifest_hash,
    task_region_snapshot_authority_view,
)
from orchestrator.graph_runtime.controller import GraphCommandResult, GraphController
from orchestrator.graph_runtime.dispatch import (
    GraphDispatchContext,
    assemble_graph_dispatch_context,
)
from orchestrator.graph_runtime.prompts import (
    render_graph_node_prompt,
    summarize_graph_node_prompt,
)
from orchestrator.graph_runtime.store import GraphEventStore
from orchestrator.graph_runtime.joined_reliable_plan_driver import run_joined_driver_case


class ReliablePlanScenarioAssertionError(AssertionError):
    """A product-path observation did not satisfy its scenario contract."""


ScenarioExecutor = Callable[
    [ReliablePlanScenarioDefinition], Awaitable[ReliablePlanScenarioObservation]
]


@dataclass(frozen=True)
class ReliablePlanQualificationRun:
    """Durable qualification facts returned by the canonical product runner."""

    qualification: ReliablePlanSkeletonQualification
    projection: GraphProjection
    accepted_receipt_record_id: str
    receipt: ReliablePlanQualificationReceipt


@dataclass(frozen=True)
class ReliablePlanJoinedCaseRun:
    """Joined failure/correction evidence from the same controller driver."""

    qualification: ReliablePlanJoinedCaseQualification
    observations: tuple[ReliablePlanJoinedCaseObservation, ...]


class _SqliteProbe:
    def __init__(self, root: Path, scenario: ReliablePlanScenarioDefinition) -> None:
        nonce = uuid4().hex[:8]
        self.run_id = f"reliable-plan-s{scenario.number}-{nonce}"
        self.clock = FakeClock()
        self.ids = SequentialIdGenerator()
        self.engine: AsyncEngine = create_engine(root / f"{self.run_id}.db")
        self.sessions: async_sessionmaker[AsyncSession] = create_session_factory(self.engine)
        self.controller = GraphController(
            self.sessions,
            self.clock,
            self.ids,
            auto_dispatch=False,
        )

    async def initialize(self) -> None:
        await init_db(self.engine)

    async def close(self) -> None:
        await self.engine.dispose()

    async def seed(self, facts: list[tuple[str, dict[str, object]]]) -> int:
        make_event = event_factory(self.run_id, "seed_compiled_events", self.clock, self.ids)
        result = await self.controller.handle_command(
            self.run_id,
            0,
            "seed_compiled_events",
            {"events": [make_event(kind, payload) for kind, payload in facts]},
        )
        _require(
            not any(event.event_type == "command_rejected" for event in result.events),
            f"controller rejected canonical scenario seed: {_event_summary(result.events)}",
        )
        return result.projection_position

    async def activate(self, position: int) -> int:
        accepted = await self.controller.handle_command(self.run_id, position, "accept_run")
        started = await self.controller.handle_command(
            self.run_id, accepted.projection_position, "start"
        )
        return started.projection_position

    async def events(self):
        async with self.sessions() as session:
            return await GraphEventStore(session).read_run(self.run_id)


class ReliablePlanProductPathRunner:
    """Run all ten incident regressions against production graph components."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._executors: dict[int, ScenarioExecutor] = {
            1: self._scenario_1,
            2: self._scenario_2,
            3: self._scenario_3,
            4: self._scenario_4,
            5: self._scenario_5,
            6: self._scenario_6,
            7: self._scenario_7,
            8: self._scenario_8,
            9: self._scenario_9,
            10: self._scenario_10,
        }

    async def execute(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        return await self._executors[scenario.number](scenario)

    async def run(self, manifest: ReliablePlanScenarioManifest) -> ReliablePlanQualificationRun:
        if manifest.contract_identity.interaction_contract == "decision-v1":
            joined = await self.run_joined_cases(canonical_decision_v1_joined_case_manifest())
            observations = tuple(
                ReliablePlanScenarioObservation(
                    number=scenario.number,
                    name=scenario.name,
                    product_path=scenario.product_path,
                    run_id=observed.run_id,
                    evidence=observed.evidence,
                )
                for scenario, observed in zip(manifest.scenarios, joined.observations, strict=True)
            )
        else:
            observations = tuple([await self.execute(scenario) for scenario in manifest.scenarios])
        probe = _SqliteProbe(self._root, manifest.scenarios[0])
        await probe.initialize()
        try:
            observation_record_ids = tuple(
                f"qualification-observation-{item.number}" for item in observations
            )
            facts: list[tuple[str, dict[str, object]]] = [
                (
                    "node_created",
                    {
                        "node_id": "qualification-runner",
                        "kind": "worker",
                        "state": "completed",
                    },
                )
            ]
            for record_id, observation in zip(observation_record_ids, observations, strict=True):
                facts.append(
                    (
                        "output_record_accepted",
                        _semantic_artifact(
                            record_id,
                            "qualification-runner",
                            "reliable_plan_scenario_observation",
                            observation.model_dump(mode="json"),
                            schema_id="reliable-plan-qualification",
                        ),
                    )
                )
            receipt_record_id = "reliable-plan-qualification-receipt"
            observation_hashes = tuple(item.observation_hash for item in observations)
            receipt = ReliablePlanQualificationReceipt(
                receipt_record_id=receipt_record_id,
                contract_identity=manifest.contract_identity,
                manifest_hash=reliable_plan_manifest_hash(manifest),
                observation_record_ids=observation_record_ids,
                observation_hashes=observation_hashes,
                evidence_hash=_hash_values(observation_hashes),
            )
            facts.append(
                (
                    "output_record_accepted",
                    _semantic_artifact(
                        receipt_record_id,
                        "qualification-runner",
                        "reliable_plan_qualification_receipt",
                        receipt.model_dump(mode="json"),
                        schema_id="reliable-plan-qualification",
                        source_record_ids=list(observation_record_ids),
                    ),
                )
            )
            await probe.seed(facts)
            projection = await probe.controller.read_projection(probe.run_id)
            qualification, accepted_receipt = qualification_from_accepted_records(
                manifest,
                projection,
                receipt_record_id,
            )
            return ReliablePlanQualificationRun(
                qualification=qualification,
                projection=projection,
                accepted_receipt_record_id=receipt_record_id,
                receipt=accepted_receipt,
            )
        finally:
            await probe.close()

    async def run_joined_cases(
        self, manifest: ReliablePlanJoinedCaseManifest
    ) -> ReliablePlanJoinedCaseRun:
        """Run the fixed joined correction/failure set on the real graph driver."""
        observations: list[ReliablePlanJoinedCaseObservation] = []
        for case in manifest.cases:
            if case.case_id == "compatibility":
                observations.append(_joined_compatibility_observation(manifest))
                continue
            observed = await run_joined_driver_case(self._root, case.case_id)
            _require(observed.outcome == case.expected_outcome, " | ".join(observed.evidence))
            expected_causes = {
                "single-batch": "typed_plan_completed_without_intervention",
                "dependent-batches": "typed_plan_completed_without_intervention",
                "plan-amendment": "revised_plan_independently_verified_and_completed",
                "smoke": "typed_plan_completed_without_intervention",
                "correction": "failed_check_repaired_by_accepted_corrective_work",
                "blocked": "required_operator_input_absent",
                "cancellation-restart": "runner_shutdown_recovered_then_cancelled_after_restart",
                "defective-candidate": "mandatory_candidate_check_failed_and_escalated",
                "defective-verifier": "independent_verifier_failed_and_escalated",
            }
            _require(
                observed.outcome_cause == expected_causes[case.case_id],
                " | ".join(observed.evidence),
            )
            completed = observed.outcome == "completed"
            bounded_terminal = (
                observed.active_lease_count == 0
                and observed.suspended_lease_count == 0
                and observed.owned_process_count == 0
                and observed.pending_outbox_count == 0
            )
            _require(bounded_terminal, " | ".join(observed.evidence))
            if completed:
                _require(observed.graph_state == "completed", " | ".join(observed.evidence))
                _require(
                    observed.workflow_status.value == "completed", " | ".join(observed.evidence)
                )
                _require(observed.exact_candidate, " | ".join(observed.evidence))
                _require(observed.clean_checkout, " | ".join(observed.evidence))
                _require(not observed.unfinished_node_ids, " | ".join(observed.evidence))
                _require(observed.finalized_execution_count > 0, " | ".join(observed.evidence))
            elif observed.outcome == "blocked":
                _require(observed.workflow_status.value == "paused", " | ".join(observed.evidence))
                _require(observed.graph_state == "active", " | ".join(observed.evidence))
            observations.append(
                ReliablePlanJoinedCaseObservation(
                    case_id=case.case_id,
                    run_id=observed.run_id,
                    outcome=observed.outcome,
                    passed=True,
                    false_acceptance=False,
                    intervention_recorded=observed.intervention_recorded,
                    intentionally_unexecuted_node_ids=(),
                    unfinished_node_ids=observed.unfinished_node_ids,
                    evidence=observed.evidence,
                    contract_identity=manifest.contract_identity,
                    finalized_execution_count=observed.finalized_execution_count,
                    active_lease_count=observed.active_lease_count,
                    suspended_lease_count=observed.suspended_lease_count,
                    owned_process_count=observed.owned_process_count,
                    pending_outbox_count=observed.pending_outbox_count,
                    candidate_paths=observed.candidate_paths,
                    exact_candidate=observed.exact_candidate,
                    clean_checkout=observed.clean_checkout,
                    graph_state=observed.graph_state,
                    workflow_status=observed.workflow_status,
                )
            )
        qualification = ReliablePlanJoinedCaseQualification(
            manifest=manifest,
            observations=tuple(observations),
        )
        return ReliablePlanJoinedCaseRun(
            qualification=qualification,
            observations=tuple(observations),
        )

    async def _scenario_1(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed([("node_created", _planner_node())])
            rejected = await probe.controller.handle_command(
                probe.run_id,
                position,
                "submit_patch",
                {
                    "patch_id": "discovery-write-escalation",
                    "base_graph_position": position,
                    "ops": [
                        {
                            "op": "create_node",
                            "node": {
                                **_executable_worker(
                                    "worker-discovery", "discovery", access_mode="write"
                                ),
                                "role": "discovery",
                                "semantic_stage": "discovery",
                                "semantic_schema_id": "inventory",
                                "semantic_schema_version": 1,
                                "outputs": [
                                    {"port": "semantic_artifact", "schema": "SemanticArtifact"}
                                ],
                            },
                        }
                    ],
                },
                context=_patch_context(probe.run_id, position),
            )
            reason = str(rejected.events[0].payload.get("reason"))
            _require(rejected.events[0].event_type == "graph_patch_rejected", reason)
            _require("discovery" in reason and "write" in reason, reason)
            return _passed(scenario, probe.run_id, f"patch_rejection={reason}")
        finally:
            await probe.close()

    async def _scenario_2(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        observations: list[str] = []
        final_run_id = ""
        for outcome in (None, "failed", "passed"):
            probe = _SqliteProbe(self._root, scenario)
            await probe.initialize()
            try:
                final_run_id = probe.run_id
                facts = _plan_handoff_facts(outcome)
                position = await probe.seed(facts)
                position = await probe.activate(position)
                scheduled = await probe.controller.handle_command(
                    probe.run_id,
                    position,
                    "schedule_tick",
                    {"max_grants": 4, "lease_seconds": 60, "base_snapshot_id": "baseline"},
                )
                leased = {
                    str(event.payload["node_id"])
                    for event in scheduled.events
                    if event.event_type == "lease_granted"
                }
                if outcome == "passed":
                    _require("worker-implementation" in leased, f"leased={sorted(leased)}")
                else:
                    _require("worker-implementation" not in leased, f"leased={sorted(leased)}")
                observations.append(f"{outcome or 'missing'}:leased={sorted(leased)}")
            finally:
                await probe.close()
        return _passed(scenario, final_run_id, *observations)

    async def _scenario_3(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed(
                [
                    (
                        "node_created",
                        {
                            "node_id": "routine-snapshot",
                            "kind": "artifact",
                            "role": "routine_snapshot",
                            "state": "completed",
                        },
                    ),
                    (
                        "node_created",
                        {
                            **_planner_node(),
                            "state": "planned",
                            "base_snapshot_selection": "run_baseline",
                        },
                    ),
                    (
                        "node_created",
                        {"node_id": "plan-source", "kind": "worker", "state": "completed"},
                    ),
                    (
                        "node_created",
                        {
                            "node_id": "plan-verifier",
                            "kind": "verifier",
                            "state": "planned",
                            "semantic_stage": "plan_verification",
                            "task_region_id": "region-plan-verification",
                            "objective": "Verify the accepted implementation plan.",
                            "acceptance": ["the plan preserves the incident requirement"],
                            "rubric": ["the plan preserves the incident requirement"],
                            "base_snapshot_selection": "run_baseline",
                            "semantic_schema_id": "ordered-plan",
                            "semantic_schema_version": 1,
                        },
                    ),
                    (
                        "node_created",
                        {
                            "node_id": "requirement",
                            "kind": "requirement",
                            "state": "completed",
                        },
                    ),
                    (
                        "output_record_accepted",
                        _semantic_schema_declaration("ordered-plan", "implementation_plan"),
                    ),
                    (
                        "output_record_accepted",
                        _semantic_schema_declaration(
                            "plan-amendment", "plan_amendment", record_id="schema-plan-amendment"
                        ),
                    ),
                    (
                        "output_record_accepted",
                        _semantic_artifact(
                            "accepted-plan",
                            "plan-source",
                            "implementation_plan",
                            {"batches": [{"batch_id": "batch-1"}, {"batch_id": "batch-2"}]},
                        ),
                    ),
                    ("output_record_accepted", _requirement_record(source="routine")),
                    (
                        "edge_created",
                        {
                            "edge_id": "edge-plan-to-verifier",
                            "from_node_id": "plan-source",
                            "from_port": "semantic_artifact",
                            "to_node_id": "plan-verifier",
                            "to_port": "semantic_artifact",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "semantic_artifact",
                                "schema": "SemanticArtifact",
                                "semantic_schema_id": "ordered-plan",
                                "semantic_schema_version": 1,
                                "authority_status": "accepted",
                            },
                            "prompt_hydration_policy": "structured_json",
                        },
                    ),
                    (
                        "edge_created",
                        {
                            "edge_id": "edge-requirement-to-verifier",
                            "from_node_id": "requirement",
                            "from_port": "requirement",
                            "to_node_id": "plan-verifier",
                            "to_port": "requirement_1",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "requirement_record",
                                "schema": "RequirementRecord",
                            },
                            "prompt_hydration_policy": "structured_json",
                        },
                    ),
                    (
                        "input_bound",
                        {
                            "edge_id": "edge-plan-to-verifier",
                            "to_node_id": "plan-verifier",
                            "to_port": "semantic_artifact",
                            "record_ids": ["accepted-plan"],
                            "bound_at_position": 1,
                        },
                    ),
                    (
                        "input_bound",
                        {
                            "edge_id": "edge-requirement-to-verifier",
                            "to_node_id": "plan-verifier",
                            "to_port": "requirement_1",
                            "record_ids": ["req-incident"],
                            "bound_at_position": 1,
                        },
                    ),
                ]
            )
            generic = await probe.controller.handle_command(
                probe.run_id,
                position,
                "submit_patch",
                {
                    "patch_id": "generic-collapse",
                    "base_graph_position": position,
                    "ops": [
                        {
                            "op": "create_node",
                            "node": {
                                **_executable_worker(
                                    "generic-worker", "generic", access_mode="write"
                                ),
                            },
                        }
                    ],
                },
                context=_patch_context(probe.run_id, position),
            )
            reason = str(generic.events[0].payload.get("reason"))
            _require("must use effectful_batch semantics" in reason, reason)

            position = await probe.activate(generic.projection_position)
            position, verifier_lease = await _lease_node(
                probe,
                position,
                "plan-verifier",
            )
            verification = _verification_record("passed")
            # The controller owns evidence lineage.  Omitting the derived citation
            # fields here proves that the accepted report is enriched from the
            # verifier's exact bound plan and requirement records.
            for field in (
                "candidate_record_id",
                "candidate_record_ids",
                "evaluated_record_ids",
            ):
                verification.pop(field, None)
            accepted_verification = await _submit_records(
                probe,
                position,
                verifier_lease,
                [verification],
                callback_id="plan-verification",
            )
            _require(
                accepted_verification.events[0].event_type == "callback_accepted"
                and any(
                    event.event_type == "output_record_accepted"
                    and event.payload.get("record_id") == "verification-plan"
                    and event.payload.get("evaluated_record_ids")
                    == ["req-incident", "accepted-plan"]
                    for event in accepted_verification.events
                ),
                _event_summary(accepted_verification.events),
            )
            position = accepted_verification.projection_position
            position, planner_lease = await _lease_node(
                probe,
                position,
                "planner-1",
            )
            amendment = _semantic_artifact(
                "amendment",
                "planner-1",
                "plan_amendment",
                {"amends_plan_record_id": "accepted-plan", "batch_ids": ["batch-combined"]},
                schema_id="plan-amendment",
                source_record_ids=["accepted-plan", "verification-plan"],
                provenance={
                    "source_plan_record_id": "accepted-plan",
                    "plan_verification_record_id": "verification-plan",
                },
            )
            accepted_amendment = await _submit_records(
                probe,
                position,
                planner_lease,
                [amendment],
                callback_id="plan-amendment",
            )
            _require(
                accepted_amendment.events[0].event_type == "callback_accepted"
                and any(
                    event.event_type == "output_record_accepted"
                    and event.payload.get("record_id") == "amendment"
                    for event in accepted_amendment.events
                ),
                _event_summary(accepted_amendment.events),
            )
            projection = await probe.controller.read_projection(probe.run_id)
            accepted_record = projection.records.by_id.get("amendment")
            _require(
                accepted_record is not None,
                "controller did not persist the authoritative plan amendment",
            )

            amended_batch = await probe.controller.handle_command(
                probe.run_id,
                accepted_amendment.projection_position,
                "submit_patch",
                {
                    "patch_id": "amended-effectful-batch",
                    "base_graph_position": accepted_amendment.projection_position,
                    "macro_invocations": [
                        {
                            "macro": "create_effectful_batch",
                            "args": {
                                "region_id": "region-batch-combined",
                                "batch_id": "batch-combined",
                                "plan_source_node_id": "plan-source",
                                "plan_verification_source_node_id": "plan-verifier",
                                "semantic_schema_id": "ordered-plan",
                                "semantic_schema_version": 1,
                                "objective": "Implement the accepted combined batch.",
                                "acceptance": ["combined batch checks pass"],
                                "checks": [
                                    {
                                        "check_id": "check-batch-combined",
                                        "command_definition": {
                                            "id": "check-batch-combined",
                                            "cmd": "printf amended-batch-check",
                                        },
                                    }
                                ],
                                "rubric": ["candidate satisfies the amended batch"],
                                "planning_horizon": 1,
                                "accepted_plan_amendment_record_id": "amendment",
                            },
                        }
                    ],
                },
                context=_patch_context(
                    probe.run_id,
                    accepted_amendment.projection_position,
                ),
            )
            _require(
                any(event.event_type == "graph_patch_accepted" for event in amended_batch.events),
                _event_summary(amended_batch.events),
            )
            return _passed(
                scenario,
                probe.run_id,
                f"generic_rejected={reason}",
                "controller_accepted_amendment=accepted-plan+verification-plan",
                "amended_effectful_batch=worker+check+verifier",
            )
        finally:
            await probe.close()

    async def _scenario_4(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe, context = await self._prompt_probe(scenario, corrective=False)
        try:
            prompt = render_graph_node_prompt(context)
            summary = summarize_graph_node_prompt(context)
            _require("REQ-incident: preserve accepted stages" in prompt, "bound requirement absent")
            _require("accepted-plan" in prompt, "bound evidence absent")
            hydrated_ids = sorted(
                str(record["record_id"])
                for records in summary["bound_records"].values()
                for record in records
                if record.get("prompt_disposition") == "hydrated"
            )
            _require(
                hydrated_ids == ["accepted-plan", "req-incident"],
                json.dumps(summary, sort_keys=True),
            )
            return _passed(
                scenario,
                probe.run_id,
                "prompt includes exact bound requirement",
                "prompt summary reports hydrated evidence IDs",
            )
        finally:
            await probe.close()

    async def _scenario_5(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe, context = await self._prompt_probe(scenario, corrective=True)
        try:
            prompt = render_graph_node_prompt(context)
            for value in (
                "verification-failed",
                "check-failed",
                "gap-corrective",
                "REQ-incident",
                "grade-C",
                "exit=1",
            ):
                _require(value in prompt, f"corrective prompt missing {value}")
            return _passed(
                scenario,
                probe.run_id,
                "corrective prompt contains exact immutable verification/check/gap payloads",
            )
        finally:
            await probe.close()

    async def _scenario_6(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed(
                [
                    (
                        "node_created",
                        {
                            "node_id": "routine-snapshot",
                            "kind": "artifact",
                            "role": "routine_snapshot",
                            "state": "completed",
                        },
                    ),
                    (
                        "node_created",
                        {
                            **_executable_worker("artifact-producer", "artifact-producer"),
                            "base_snapshot_selection": "run_baseline",
                        },
                    ),
                    (
                        "node_created",
                        {
                            **_executable_worker("artifact-consumer", "artifact-consumer"),
                            "base_snapshot_selection": "run_baseline",
                            "inputs": [
                                {
                                    "port": "semantic_artifact",
                                    "schema": "SemanticArtifact",
                                    "required": True,
                                }
                            ],
                        },
                    ),
                    (
                        "edge_created",
                        {
                            "edge_id": "edge-exact-artifact",
                            "from_node_id": "artifact-producer",
                            "from_port": "semantic_artifact",
                            "to_node_id": "artifact-consumer",
                            "to_port": "semantic_artifact",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "semantic_artifact",
                                "schema": "SemanticArtifact",
                                "semantic_schema_id": "ordered-plan",
                                "semantic_schema_version": 1,
                                "authority_status": "accepted",
                            },
                        },
                    ),
                    (
                        "output_record_accepted",
                        _semantic_schema_declaration(
                            "ordered-plan",
                            "implementation_plan",
                        ),
                    ),
                    (
                        "output_record_accepted",
                        _semantic_schema_declaration(
                            "different-plan",
                            "implementation_plan",
                            record_id="schema-different-plan",
                        ),
                    ),
                ]
            )
            position = await probe.activate(position)
            position, producer_lease = await _lease_node(
                probe,
                position,
                "artifact-producer",
            )
            impostors = [
                _candidate_record(
                    "candidate-impostor", "artifact-producer", "region-artifact-producer", 1
                ),
                _file_state_record(
                    "file-state-impostor",
                    "artifact-producer",
                    "candidate-impostor",
                    "snapshot-impostor",
                    "baseline",
                    "region-artifact-producer",
                ),
                _semantic_artifact(
                    "wrong-schema",
                    "artifact-producer",
                    "implementation_plan",
                    {"batches": []},
                    schema_id="different-plan",
                ),
            ]
            accepted_impostors: list[str] = []
            for index, record in enumerate(impostors, start=1):
                callback = await _submit_records(
                    probe,
                    position,
                    producer_lease,
                    [record],
                    callback_id=f"impostor-{index}",
                    complete_node=False,
                )
                position = callback.projection_position
                record_id = cast(str, record["record_id"])
                _require(
                    callback.events[0].event_type == "callback_accepted"
                    and any(
                        event.payload.get("record_id") == record_id
                        for event in callback.events
                        if event.event_type in {"output_record_accepted", "file_state_accepted"}
                    )
                    and not any(
                        event.event_type == "input_bound"
                        and event.payload.get("to_node_id") == "artifact-consumer"
                        for event in callback.events
                    ),
                    _event_summary(callback.events),
                )
                scheduled = await probe.controller.handle_command(
                    probe.run_id,
                    position,
                    "schedule_tick",
                    {
                        "max_grants": 1,
                        "lease_seconds": 60,
                        "base_snapshot_id": "baseline",
                        "priorities": {"artifact-consumer": 100},
                    },
                )
                position = scheduled.projection_position
                _require(
                    not any(
                        event.event_type == "lease_granted"
                        and event.payload.get("node_id") == "artifact-consumer"
                        for event in scheduled.events
                    ),
                    _event_summary(scheduled.events),
                )
                accepted_impostors.append(record_id)

            exact = _semantic_artifact(
                "exact-artifact",
                "artifact-producer",
                "implementation_plan",
                {"batches": [{"batch_id": "batch-1"}]},
            )
            accepted_exact = await _submit_records(
                probe,
                position,
                producer_lease,
                [exact],
                callback_id="exact-artifact",
                complete_node=False,
            )
            _require(
                accepted_exact.events[0].event_type == "callback_accepted"
                and any(
                    event.event_type == "input_bound"
                    and event.payload.get("to_node_id") == "artifact-consumer"
                    and event.payload.get("record_ids") == ["exact-artifact"]
                    for event in accepted_exact.events
                ),
                _event_summary(accepted_exact.events),
            )
            scheduled = await probe.controller.handle_command(
                probe.run_id,
                accepted_exact.projection_position,
                "schedule_tick",
                {
                    "max_grants": 1,
                    "lease_seconds": 60,
                    "base_snapshot_id": "baseline",
                    "priorities": {"artifact-consumer": 100},
                },
            )
            consumer_lease = next(
                (
                    event
                    for event in scheduled.events
                    if event.event_type == "lease_granted"
                    and event.payload.get("node_id") == "artifact-consumer"
                ),
                None,
            )
            _require(consumer_lease is not None, _event_summary(scheduled.events))
            return _passed(
                scenario,
                probe.run_id,
                f"controller_accepted_nonmatching_records={accepted_impostors}",
                "semantic_input_rejected=candidate,file-state,different-plan",
                "exact_artifact_bound_and_consumer_leased=exact-artifact",
            )
        finally:
            await probe.close()

    async def _scenario_7(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed(_snapshot_scenario_facts())
            position = await probe.activate(position)

            position, worker_one_lease = await _lease_node(
                probe,
                position,
                "worker-snapshot-one",
            )
            candidate_one = await _submit_records(
                probe,
                position,
                worker_one_lease,
                _candidate_snapshot_records("one", "baseline", attempt_number=1),
                callback_id="candidate-one",
            )
            position, verifier_one_lease = await _lease_node(
                probe,
                candidate_one.projection_position,
                "verifier-snapshot-one",
            )
            verdict_one = await _submit_records(
                probe,
                position,
                verifier_one_lease,
                [
                    _verification_record(
                        "passed",
                        record_id="verification-one",
                        producer="verifier-snapshot-one",
                        candidate_id="candidate-one",
                        grades=[],
                        evaluated_record_ids=["candidate-one", "file-state-one"],
                    )
                ],
                callback_id="verdict-one",
            )

            position, accepted_one_lease = await _lease_node(
                probe,
                verdict_one.projection_position,
                "downstream-accepted-one",
            )
            _require(
                accepted_one_lease["base_snapshot_id"] == "snapshot-one",
                f"accepted downstream base={accepted_one_lease['base_snapshot_id']}",
            )

            position, worker_two_lease = await _lease_node(
                probe,
                position,
                "worker-snapshot-two",
            )
            candidate_two = await _submit_records(
                probe,
                position,
                worker_two_lease,
                _candidate_snapshot_records("two", "snapshot-one", attempt_number=2),
                callback_id="candidate-two",
            )
            position, verifier_two_lease = await _lease_node(
                probe,
                candidate_two.projection_position,
                "verifier-snapshot-two",
            )
            verdict_two = await _submit_records(
                probe,
                position,
                verifier_two_lease,
                [
                    _verification_record(
                        "failed",
                        record_id="verification-two",
                        producer="verifier-snapshot-two",
                        candidate_id="candidate-two",
                        grades=[],
                        evaluated_record_ids=["candidate-two", "file-state-two"],
                    )
                ],
                callback_id="verdict-two",
            )

            position, rejected_two_lease = await _lease_node(
                probe,
                verdict_two.projection_position,
                "downstream-rejected-two",
            )
            _require(
                rejected_two_lease["base_snapshot_id"] == "snapshot-two",
                f"explicit rejected base={rejected_two_lease['base_snapshot_id']}",
            )

            position, worker_three_lease = await _lease_node(
                probe,
                position,
                "worker-snapshot-three",
            )
            candidate_three = await _submit_records(
                probe,
                position,
                worker_three_lease,
                _candidate_snapshot_records("three", "snapshot-one", attempt_number=3),
                callback_id="candidate-three",
            )
            position, verifier_three_lease = await _lease_node(
                probe,
                candidate_three.projection_position,
                "verifier-snapshot-three",
            )
            verdict_three = await _submit_records(
                probe,
                position,
                verifier_three_lease,
                [
                    _verification_record(
                        "passed",
                        record_id="verification-three",
                        producer="verifier-snapshot-three",
                        candidate_id="candidate-three",
                        grades=[],
                        evaluated_record_ids=["candidate-three", "file-state-three"],
                    )
                ],
                callback_id="verdict-three",
            )

            _, accepted_three_lease = await _lease_node(
                probe,
                verdict_three.projection_position,
                "downstream-accepted-three",
            )
            _require(
                accepted_three_lease["base_snapshot_id"] == "snapshot-three",
                f"corrected accepted base={accepted_three_lease['base_snapshot_id']}",
            )
            projection = await probe.controller.read_projection(probe.run_id)
            authority = task_region_snapshot_authority_view(projection)["region-snapshots"]
            _require(
                authority.accepted_snapshot is not None
                and authority.accepted_snapshot.snapshot_id == "snapshot-three",
                "accepted correction did not advance authority",
            )
            _require(
                [item.snapshot_id for item in authority.rejected_snapshots] == ["snapshot-two"],
                "rejected correction evidence missing",
            )
            return _passed(
                scenario,
                probe.run_id,
                "accepted_base_before_correction=snapshot-one",
                "explicit_rejected_correction_base=snapshot-two",
                "accepted_base_after_correction=snapshot-three",
                "candidate+file-state+verdict lineage persisted by callbacks",
            )
        finally:
            await probe.close()

    async def _scenario_8(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed(_final_gate_facts())
            position = await probe.activate(position)

            position, planner_lease = await _lease_node(probe, position, "planner-plan")
            accepted_plan = await _submit_records(
                probe,
                position,
                planner_lease,
                [
                    _semantic_artifact(
                        "accepted-plan",
                        "planner-plan",
                        "implementation_plan",
                        {"batches": [{"batch_id": "batch-1"}]},
                    )
                ],
                callback_id="accepted-plan",
            )
            _require(
                any(
                    event.event_type == "input_bound"
                    and event.payload.get("to_node_id") == "worker-batch"
                    for event in accepted_plan.events
                ),
                _event_summary(accepted_plan.events),
            )
            position, worker_lease = await _lease_node(
                probe,
                accepted_plan.projection_position,
                "worker-batch",
            )
            candidate = await _submit_records(
                probe,
                position,
                worker_lease,
                [
                    _file_state_record(
                        "file-state-batch",
                        "worker-batch",
                        "candidate-batch",
                        "snapshot-batch",
                        "baseline",
                        "region-batch-1",
                    ),
                    _candidate_record(
                        "candidate-batch",
                        "worker-batch",
                        "region-batch-1",
                        1,
                        file_state_record_id="file-state-batch",
                    ),
                ],
                callback_id="candidate-batch",
            )
            position, check_lease = await _lease_node(
                probe,
                candidate.projection_position,
                "check-batch",
            )
            checked = await _submit_records(
                probe,
                position,
                check_lease,
                [
                    _passed_check_record(
                        base_snapshot_id=str(check_lease["base_snapshot_id"]),
                        execution_id=str(check_lease["execution_id"]),
                    )
                ],
                callback_id="check-batch",
            )
            _require(
                any(event.event_type == "callback_accepted" for event in checked.events),
                _event_summary(checked.events),
            )

            missing_batch = await probe.controller.handle_command(
                probe.run_id,
                checked.projection_position,
                "evaluate_final_gate",
                {"node_id": "gate-final"},
            )
            missing_batch_blockers = _completion_blocker_kinds(missing_batch.events)
            _require(
                "missing_declared_batch_verification" in missing_batch_blockers,
                f"blockers={sorted(missing_batch_blockers)}",
            )

            position, batch_verifier_lease = await _lease_node(
                probe,
                missing_batch.projection_position,
                "batch-verifier",
            )
            batch_verdict = await _submit_records(
                probe,
                position,
                batch_verifier_lease,
                [
                    _verification_record(
                        "passed",
                        record_id="batch-report",
                        producer="batch-verifier",
                        candidate_id="candidate-batch",
                        grades=[],
                        evaluated_record_ids=[
                            "check-result-batch",
                            "candidate-batch",
                            "file-state-batch",
                        ],
                    )
                ],
                callback_id="batch-verdict",
            )
            _require(
                any(event.event_type == "verification_passed" for event in batch_verdict.events),
                _event_summary(batch_verdict.events),
            )
            projection = await probe.controller.read_projection(probe.run_id)
            batch_authority = task_region_snapshot_authority_view(projection)["region-batch-1"]
            _require(
                batch_authority.accepted_snapshot is not None
                and batch_authority.accepted_snapshot.candidate_id == "candidate-batch",
                "passing batch callback did not produce task-region acceptance",
            )

            missing_audit = await probe.controller.handle_command(
                probe.run_id,
                batch_verdict.projection_position,
                "evaluate_final_gate",
                {"node_id": "gate-final"},
            )
            missing_audit_blockers = _completion_blocker_kinds(missing_audit.events)
            _require(
                "missing_final_independent_audit" in missing_audit_blockers
                and "missing_declared_batch_verification" not in missing_audit_blockers,
                f"blockers={sorted(missing_audit_blockers)}",
            )

            position, acceptance_lease = await _lease_node(
                probe,
                missing_audit.projection_position,
                "final-acceptance",
            )
            accepted = await _submit_records(
                probe,
                position,
                acceptance_lease,
                [_passed_final_acceptance_record()],
                callback_id="final-acceptance",
            )
            _require(
                any(
                    event.event_type == "output_record_accepted"
                    and event.payload.get("record_id") == "final-acceptance-report"
                    for event in accepted.events
                ),
                _event_summary(accepted.events),
            )

            position, audit_lease = await _lease_node(
                probe,
                accepted.projection_position,
                "final-audit",
            )
            audit_record = _verification_record(
                "passed",
                record_id="audit-report",
                producer="final-audit",
                candidate_id="batch-report",
                grades=[],
                evaluated_record_ids=[
                    "final-acceptance-report",
                    "batch-report",
                    "check-result-batch",
                    "candidate-batch",
                    "file-state-batch",
                ],
            )
            audit_record.pop("candidate_record_id")
            audit_record["candidate_record_ids"] = ["batch-report", "candidate-batch"]
            audit_record["file_state_record_ids"] = ["file-state-batch"]
            audited = await _submit_records(
                probe,
                position,
                audit_lease,
                [audit_record],
                callback_id="final-audit",
            )
            _require(
                any(
                    event.event_type == "input_bound"
                    and event.payload.get("to_node_id") == "gate-final"
                    and event.payload.get("to_port") == "final_audit"
                    and event.payload.get("record_ids") == ["audit-report"]
                    for event in audited.events
                ),
                _event_summary(audited.events),
            )
            completed = await probe.controller.handle_command(
                probe.run_id,
                audited.projection_position,
                "evaluate_final_gate",
                {"node_id": "gate-final"},
            )
            completion = next(
                event
                for event in completed.events
                if event.event_type == "output_record_accepted"
                and event.payload.get("record_type") == "completion_decision"
            )
            _require(
                completion.payload["value"] == {"status": "passed", "blockers": []},
                json.dumps(completion.payload["value"], sort_keys=True),
            )
            return _passed(
                scenario,
                probe.run_id,
                "missing_batch_blocked=missing_declared_batch_verification",
                "batch_callback_accepted_candidate+file-state+check=task-region-accepted",
                "batch_bound_missing_audit_blocked=missing_final_independent_audit",
                "exact_bound_batch+audit_callbacks=passed",
            )
        finally:
            await probe.close()

    async def _scenario_9(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            position = await probe.seed(
                [("node_created", _executable_worker("worker-retry", "retry"))]
            )
            position = await probe.activate(position)
            scheduled = await probe.controller.handle_command(
                probe.run_id,
                position,
                "schedule_tick",
                {"max_grants": 1, "lease_seconds": 60, "base_snapshot_id": "baseline"},
            )
            first = next(event for event in scheduled.events if event.event_type == "lease_granted")
            died = await probe.controller.handle_command(
                probe.run_id,
                scheduled.projection_position,
                "agent_died",
                {
                    "lease_id": first.payload["lease_id"],
                    "execution_id": first.payload["execution_id"],
                    "reason": "missing callback",
                },
            )
            _require(
                any(event.event_type == "lease_revoked" for event in died.events),
                "missing callback did not revoke lease",
            )
            _require(
                not any(event.event_type == "runtime_retry_scheduled" for event in died.events),
                "identical immediate retry was scheduled",
            )
            _require(
                any(
                    event.event_type == "node_state_changed"
                    and event.payload.get("trigger") == "agent_died_recovery_required"
                    for event in died.events
                ),
                "missing callback did not persist typed recovery-required state",
            )

            healthy_probe = _SqliteProbe(self._root, scenario)
            await healthy_probe.initialize()
            try:
                health_position = await healthy_probe.seed(
                    [
                        (
                            "node_created",
                            {
                                "node_id": "health-check",
                                "kind": "check",
                                "state": "completed",
                            },
                        ),
                        (
                            "node_created",
                            _executable_worker("worker-healthy-retry", "healthy-retry"),
                        ),
                        ("output_record_accepted", _health_check_record()),
                    ]
                )
                health_position = await healthy_probe.activate(health_position)
                health_scheduled = await healthy_probe.controller.handle_command(
                    healthy_probe.run_id,
                    health_position,
                    "schedule_tick",
                    {"max_grants": 1, "lease_seconds": 60, "base_snapshot_id": "baseline"},
                )
                health_first = next(
                    event
                    for event in health_scheduled.events
                    if event.event_type == "lease_granted"
                )
                healthy_died = await healthy_probe.controller.handle_command(
                    healthy_probe.run_id,
                    health_scheduled.projection_position,
                    "agent_died",
                    {
                        "lease_id": health_first.payload["lease_id"],
                        "execution_id": health_first.payload["execution_id"],
                        "reason": "missing callback",
                        "health_evidence_record_id": "health-check-passed",
                    },
                )
                _require(
                    any(
                        event.event_type == "runtime_retry_scheduled"
                        and event.payload.get("health_evidence_record_id") == "health-check-passed"
                        for event in healthy_died.events
                    ),
                    "persisted health evidence did not authorize retry",
                )
                retried = await healthy_probe.controller.handle_command(
                    healthy_probe.run_id,
                    healthy_died.projection_position,
                    "schedule_tick",
                    {"max_grants": 1, "lease_seconds": 60, "base_snapshot_id": "baseline"},
                )
                second = next(
                    event for event in retried.events if event.event_type == "lease_granted"
                )
                projection = await healthy_probe.controller.read_projection(healthy_probe.run_id)
                active = [
                    lease for lease in leases_view(projection).values() if lease.state == "active"
                ]
                _require(
                    second.payload["lease_id"] != health_first.payload["lease_id"]
                    and len(active) == 1,
                    "ghost or reused lease after retry",
                )
                return _passed(
                    scenario,
                    healthy_probe.run_id,
                    f"revoked_without_retry={first.payload['lease_id']}",
                    f"healthy_retry={second.payload['lease_id']}",
                    "persisted health evidence differentiates retry; one active lease",
                )
            finally:
                await healthy_probe.close()
        finally:
            await probe.close()

    async def _scenario_10(
        self, scenario: ReliablePlanScenarioDefinition
    ) -> ReliablePlanScenarioObservation:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        try:
            worker = {
                **_executable_worker("worker-disconnected", "disconnected"),
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-orphan",
                "planning_horizon": 2,
                "inputs": [
                    {"port": "semantic_artifact", "schema": "SemanticArtifact", "required": True}
                ],
            }
            position = await probe.seed(
                [
                    (
                        "node_created",
                        {"node_id": "missing-producer", "kind": "worker", "state": "planned"},
                    ),
                    ("node_created", worker),
                    (
                        "edge_created",
                        {
                            "edge_id": "edge-missing-plan",
                            "from_node_id": "missing-producer",
                            "from_port": "semantic_artifact",
                            "to_node_id": "worker-disconnected",
                            "to_port": "semantic_artifact",
                            "required": True,
                            "accepted_record_selector": {
                                "record_type": "semantic_artifact",
                                "schema": "SemanticArtifact",
                            },
                        },
                    ),
                ]
            )
            position = await probe.activate(position)
            await probe.controller.handle_command(
                probe.run_id,
                position,
                "schedule_tick",
                {"max_grants": 1, "lease_seconds": 60, "base_snapshot_id": "baseline"},
            )
            async with probe.sessions() as session:
                store = GraphEventStore(session)
                detail = await store.read_current_node_detail_summary(
                    probe.run_id,
                    "worker-disconnected",
                )
                complete = False
                while not complete:
                    complete = await store.advance_archival_view_maintenance(
                        probe.run_id,
                        batch_size=32,
                    )
                    await session.commit()
                archival = await store.read_current_archival_view_page(
                    probe.run_id,
                    "regions",
                    after_sequence=0,
                    limit=100,
                )
            _require(detail is not None, "operator node detail missing")
            assert detail is not None
            _require(
                detail.semantic_contract["objective"] == worker["objective"], "objective hidden"
            )
            _require(detail.semantic_contract["planning_horizon"] == 2, "planning horizon hidden")
            _require(
                detail.readiness_reason is not None
                and "missing_required_input:semantic_artifact" in detail.readiness_reason,
                f"readiness={detail.readiness_reason}",
            )
            _require(archival is not None, "public archival region view missing")
            assert archival is not None
            _, region_page = archival
            disconnected = next(
                (
                    item
                    for item in region_page.items
                    if item.get("task_region_id") == "region-disconnected"
                ),
                None,
            )
            _require(disconnected is not None, "disconnected region absent from archival view")
            assert disconnected is not None
            region_json = json.dumps(disconnected, sort_keys=True)
            _require(
                "worker-disconnected" in region_json and '"kind": "pending_node"' in region_json,
                region_json,
            )
            return _passed(
                scenario,
                probe.run_id,
                f"durable_node_readiness={detail.readiness_reason}",
                f"semantic_contract_keys={sorted(detail.semantic_contract)}",
                "public_archival_region_exposes=worker-disconnected+pending_node",
            )
        finally:
            await probe.close()

    async def _prompt_probe(
        self, scenario: ReliablePlanScenarioDefinition, *, corrective: bool
    ) -> tuple[_SqliteProbe, GraphDispatchContext]:
        probe = _SqliteProbe(self._root, scenario)
        await probe.initialize()
        node_id = "worker-corrective" if corrective else "worker-bound"
        node = {**_executable_worker(node_id, "prompt"), "bound_requirement_ids": ["REQ-incident"]}
        if corrective:
            node.update({"semantic_stage": "corrective_work"})
        records = [
            ("output_record_accepted", _requirement_record()),
            (
                "output_record_accepted",
                _semantic_artifact(
                    "accepted-plan",
                    "evidence-source",
                    "implementation_plan",
                    {"batches": [{"batch_id": "batch-1"}]},
                ),
            ),
        ]
        if corrective:
            records.extend(_corrective_records())
        facts: list[tuple[str, dict[str, object]]] = [
            ("node_created", node),
            (
                "node_created",
                {"node_id": "requirement", "kind": "requirement", "state": "completed"},
            ),
            (
                "node_created",
                {"node_id": "evidence-source", "kind": "worker", "state": "completed"},
            ),
        ]
        edge_specs = [
            ("requirement", "requirement", "requirement_1", {"record_type": "requirement_record"}),
            (
                "evidence-source",
                "semantic_artifact",
                "plan",
                {"record_type": "semantic_artifact", "schema": "SemanticArtifact"},
            ),
        ]
        if corrective:
            facts.extend(
                [
                    (
                        "node_created",
                        {
                            "node_id": "candidate-source",
                            "kind": "worker",
                            "state": "completed",
                            "task_region_id": "region-prompt",
                        },
                    ),
                    (
                        "node_created",
                        {"node_id": "verifier", "kind": "verifier", "state": "completed"},
                    ),
                    ("node_created", {"node_id": "check", "kind": "check", "state": "completed"}),
                    ("node_created", {"node_id": "gap", "kind": "planner", "state": "completed"}),
                ]
            )
            edge_specs.extend(
                [
                    (
                        "verifier",
                        "verification_report",
                        "failed_verification",
                        {"record_type": "verification_report", "outcome": "failed"},
                    ),
                    (
                        "check",
                        "check_result",
                        "failed_check_1",
                        {"record_type": "check_result", "status": "failed"},
                    ),
                    (
                        "gap",
                        "classified_gap",
                        "classified_gap",
                        {
                            "record_type": "gap_classification",
                            "classification": "corrective_work_required",
                        },
                    ),
                ]
            )
        facts.extend(records)
        for index, (source, port, to_port, selector) in enumerate(edge_specs):
            facts.append(
                (
                    "edge_created",
                    {
                        "edge_id": f"edge-{index}",
                        "from_node_id": source,
                        "from_port": port,
                        "to_node_id": node_id,
                        "to_port": to_port,
                        "required": True,
                        "accepted_record_selector": selector,
                        "prompt_hydration_policy": "structured_json",
                    },
                )
            )
        bound_ids = {
            "requirement_1": ["req-incident"],
            "plan": ["accepted-plan"],
            "failed_verification": ["verification-failed"],
            "failed_check_1": ["check-failed"],
            "classified_gap": ["gap-corrective"],
        }
        for index, (_, _, to_port, _) in enumerate(edge_specs):
            facts.append(
                (
                    "input_bound",
                    {
                        "edge_id": f"edge-{index}",
                        "to_node_id": node_id,
                        "to_port": to_port,
                        "record_ids": bound_ids[to_port],
                        "bound_at_position": 1,
                    },
                )
            )
        position = await probe.seed(facts)
        position = await probe.activate(position)
        scheduled = await probe.controller.handle_command(
            probe.run_id,
            position,
            "schedule_tick",
            {"max_grants": 1, "lease_seconds": 60, "base_snapshot_id": "baseline"},
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        context = await assemble_graph_dispatch_context(
            probe.sessions,
            dispatch_item,
            worktree_path=str(self._root),
        )
        return probe, context


async def run_reliable_plan_product_path_scenarios(
    manifest: ReliablePlanScenarioManifest,
    *,
    root: Path,
) -> ReliablePlanQualificationRun:
    """Canonical all-ten deterministic qualification entry point."""
    return await ReliablePlanProductPathRunner(root).run(manifest)


async def run_reliable_plan_joined_cases(
    manifest: ReliablePlanJoinedCaseManifest,
    *,
    root: Path,
) -> ReliablePlanJoinedCaseRun:
    """Run Slice 6C's joined correction and failure cases deterministically."""
    return await ReliablePlanProductPathRunner(root).run_joined_cases(manifest)


def _joined_compatibility_observation(
    manifest: ReliablePlanJoinedCaseManifest,
) -> ReliablePlanJoinedCaseObservation:
    legacy = canonical_reliable_plan_scenario_manifest()
    legacy_round_trip = ReliablePlanScenarioManifest.model_validate_json(legacy.model_dump_json())
    decision_identity_round_trip = ReliablePlanContractIdentity.model_validate_json(
        manifest.contract_identity.model_dump_json()
    )
    _require(
        legacy_round_trip.contract_identity.interaction_contract == "legacy",
        "legacy qualification round trip was relabeled",
    )
    _require(
        reliable_plan_manifest_hash(legacy_round_trip) == reliable_plan_manifest_hash(legacy),
        "legacy qualification hash changed during compatibility round trip",
    )
    _require(
        decision_identity_round_trip == manifest.contract_identity,
        "decision-v1 contract identity changed during compatibility round trip",
    )
    return ReliablePlanJoinedCaseObservation(
        case_id="compatibility",
        run_id="compatibility-controls",
        outcome="compatibility",
        passed=True,
        false_acceptance=False,
        intervention_recorded=False,
        intentionally_unexecuted_node_ids=("model-evaluation-node",),
        unfinished_node_ids=(),
        evidence=(
            "legacy_manifest_round_trip=legacy",
            "legacy_manifest_hash=stable",
            "decision_v1_identity=generated-schema-and-compiler-bound",
        ),
        contract_identity=manifest.contract_identity,
        finalized_execution_count=0,
        active_lease_count=0,
        suspended_lease_count=0,
        owned_process_count=0,
        pending_outbox_count=0,
        candidate_paths=(),
        exact_candidate=False,
        clean_checkout=True,
        graph_state=None,
        workflow_status=None,
    )


def _require(condition: bool, evidence: str) -> None:
    if not condition:
        raise ReliablePlanScenarioAssertionError(evidence)


def _passed(
    scenario: ReliablePlanScenarioDefinition, run_id: str, *evidence: str
) -> ReliablePlanScenarioObservation:
    _require(bool(evidence), "passing scenario requires observed evidence")
    return ReliablePlanScenarioObservation(
        number=scenario.number,
        name=scenario.name,
        product_path=scenario.product_path,
        run_id=run_id,
        evidence=tuple(evidence),
    )


def _hash_values(values: tuple[str, ...]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _patch_context(run_id: str, position: int) -> PatchCommandContext:
    return PatchCommandContext(
        run_id=run_id,
        current_graph_position=position,
        proposed_by_node_id="planner-1",
        actor_role="planner",
    )


async def _lease_node(
    probe: _SqliteProbe,
    position: int,
    node_id: str,
) -> tuple[int, dict[str, object]]:
    scheduled = await probe.controller.handle_command(
        probe.run_id,
        position,
        "schedule_tick",
        {
            "max_grants": 1,
            "lease_seconds": 60,
            "base_snapshot_id": "baseline",
            "priorities": {node_id: 100},
        },
    )
    lease = next(
        (
            event.payload
            for event in scheduled.events
            if event.event_type == "lease_granted" and event.payload.get("node_id") == node_id
        ),
        None,
    )
    _require(lease is not None, f"{node_id} not leased: {_event_summary(scheduled.events)}")
    assert lease is not None
    acknowledged = await probe.controller.handle_command(
        probe.run_id,
        scheduled.projection_position,
        "acknowledge_start",
        {
            "node_id": node_id,
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "execution_id": lease["execution_id"],
        },
    )
    _require(
        any(
            event.event_type == "node_state_changed" and event.payload.get("new_state") == "running"
            for event in acknowledged.events
        ),
        f"{node_id} start not acknowledged: {_event_summary(acknowledged.events)}",
    )
    return acknowledged.projection_position, lease


async def _submit_records(
    probe: _SqliteProbe,
    position: int,
    lease: dict[str, object],
    records: list[dict[str, object]],
    *,
    callback_id: str,
    complete_node: bool = True,
) -> GraphCommandResult:
    return await probe.controller.handle_command(
        probe.run_id,
        position,
        "submit_callback",
        {
            "node_id": lease["node_id"],
            "execution_id": lease["execution_id"],
            "lease_id": lease["lease_id"],
            "lease_generation": lease["generation"],
            "base_snapshot_id": lease["base_snapshot_id"],
            "observed_graph_position": position,
            "idempotency_key": f"{callback_id}-{lease['execution_id']}",
            "payload": {"output_records": records},
            "complete_node": complete_node,
            "new_state": "completed",
        },
    )


def _event_summary(events: Sequence[EventEnvelope]) -> str:
    return json.dumps(
        [
            {
                "event_type": event.event_type,
                "reason": event.payload.get("reason"),
                "record_id": event.payload.get("record_id"),
                "node_id": event.payload.get("node_id"),
            }
            for event in events
        ],
        sort_keys=True,
    )


def _completion_blocker_kinds(events: Sequence[EventEnvelope]) -> set[str]:
    decision = next(
        event
        for event in events
        if event.event_type == "output_record_accepted"
        and event.payload.get("record_type") == "completion_decision"
    )
    value = decision.payload.get("value")
    if not isinstance(value, dict):
        raise ReliablePlanScenarioAssertionError("completion decision value is not an object")
    blockers = cast(dict[str, object], value).get("blockers")
    if not isinstance(blockers, list):
        raise ReliablePlanScenarioAssertionError("completion decision blockers are not a list")
    kinds: set[str] = set()
    for raw_blocker in cast(list[object], blockers):
        if not isinstance(raw_blocker, dict):
            continue
        blocker = cast(dict[str, object], raw_blocker)
        kind = blocker.get("kind")
        if isinstance(kind, str):
            kinds.add(kind)
    return kinds


def _planner_node() -> dict[str, object]:
    return {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "completed"}


def _executable_worker(
    node_id: str,
    region: str,
    *,
    access_mode: str = "read_only",
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "kind": "worker",
        "role": "builder",
        "state": "planned",
        "task_region_id": f"region-{region}",
        "candidate_id": f"candidate-{region}",
        "attempt_number": 1,
        "objective": f"Execute {region} contract",
        "work_mode": "implementation",
        "access_mode": access_mode,
        "effect_contract": (
            "read_only_semantic" if access_mode == "read_only" else "effectful_write"
        ),
        "scope": f"scope-{region}",
        "acceptance": [f"{region} accepted"],
        "invariants": ["preserve accepted evidence"],
        "prohibited_actions": ["ignore bound requirements"],
        "base_snapshot_selection": "run_baseline",
    }


def _semantic_artifact(
    record_id: str,
    producer: str,
    role: str,
    content: dict[str, object],
    *,
    schema_id: str = "ordered-plan",
    source_record_ids: list[str] | None = None,
    provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "record_kind": "graph_record",
        "record_type": "semantic_artifact",
        "schema_version": 1,
        "producer_node_id": producer,
        "port": "semantic_artifact",
        "schema": "SemanticArtifact",
        "value": {
            "semantic_role": role,
            "schema_id": schema_id,
            "schema_version": 1,
            "content": content,
            "provenance": provenance or {},
            "source_record_ids": source_record_ids or [],
            "requirement_ids": ["REQ-incident"],
            "validation_status": "validated",
            "authority_status": "accepted",
        },
    }


def _semantic_schema_declaration(
    schema_id: str,
    semantic_role: str,
    *,
    record_id: str = "semantic-schema-ordered-plan-v1",
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "record_kind": "graph_record",
        "record_type": "semantic_schema_declaration",
        "schema_version": 1,
        "producer_node_id": "routine-snapshot",
        "port": "semantic_schema_declaration",
        "schema": "SemanticSchemaDeclaration",
        "value": {
            "schema_id": schema_id,
            "version": 1,
            "semantic_role": semantic_role,
            "json_schema": {"type": "object"},
            "authority": "routine_snapshot",
        },
    }


def _verification_record(
    outcome: str,
    *,
    record_id: str = "verification-plan",
    producer: str = "plan-verifier",
    candidate_id: str = "accepted-plan",
    grades: list[dict[str, str]] | None = None,
    evaluated_record_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": producer,
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": candidate_id,
        "candidate_record_id": candidate_id,
        "candidate_record_ids": [candidate_id],
        "outcome": outcome,
        "evaluated_record_ids": evaluated_record_ids or [candidate_id],
        "value": {
            "outcome": outcome,
            "grades": grades
            if grades is not None
            else [
                {
                    "requirement_id": "REQ-incident",
                    "grade": "grade-C" if outcome == "failed" else "grade-A",
                    "reason": "exact grade",
                }
            ],
        },
    }


def _requirement_record(*, source: str = "incident contract") -> dict[str, object]:
    return {
        "record_id": "req-incident",
        "record_kind": "graph_record",
        "record_type": "requirement_record",
        "producer_node_id": "requirement",
        "port": "requirement",
        "schema": "RequirementRecord",
        "value": {
            "id": "REQ-incident",
            "text": "preserve accepted stages",
            "source": source,
        },
    }


def _plan_handoff_facts(outcome: str | None) -> list[tuple[str, dict[str, object]]]:
    worker = {
        **_executable_worker("worker-implementation", "implementation", access_mode="write"),
    }
    facts: list[tuple[str, dict[str, object]]] = [
        (
            "node_created",
            {"node_id": "discovery", "kind": "worker", "role": "discovery", "state": "completed"},
        ),
        (
            "node_created",
            {
                "node_id": "plan-verifier",
                "kind": "verifier",
                "state": "completed",
                "semantic_stage": "plan_verification",
            },
        ),
        ("node_created", worker),
        (
            "edge_created",
            {
                "edge_id": "edge-plan",
                "from_node_id": "discovery",
                "from_port": "semantic_artifact",
                "to_node_id": "worker-implementation",
                "to_port": "semantic_artifact",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "semantic_artifact",
                    "schema": "SemanticArtifact",
                    "authority_status": "accepted",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-verification",
                "from_node_id": "plan-verifier",
                "from_port": "verification_report",
                "to_node_id": "worker-implementation",
                "to_port": "verification_report",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "verification_report",
                    "schema": "VerificationReport",
                    "outcome": "passed",
                },
            },
        ),
    ]
    if outcome is not None:
        facts.append(
            (
                "output_record_accepted",
                _semantic_artifact(
                    "accepted-plan",
                    "discovery",
                    "implementation_plan",
                    {"batches": [{"batch_id": "batch-1"}]},
                ),
            )
        )
        facts.append(("output_record_accepted", _verification_record(outcome)))
        facts.append(
            (
                "input_bound",
                {
                    "edge_id": "edge-plan",
                    "to_node_id": "worker-implementation",
                    "to_port": "semantic_artifact",
                    "record_ids": ["accepted-plan"],
                    "bound_at_position": 1,
                },
            )
        )
        if outcome == "passed":
            facts.append(
                (
                    "input_bound",
                    {
                        "edge_id": "edge-verification",
                        "to_node_id": "worker-implementation",
                        "to_port": "verification_report",
                        "record_ids": ["verification-plan"],
                        "bound_at_position": 1,
                    },
                )
            )
    return facts


def _corrective_records() -> list[tuple[str, dict[str, object]]]:
    check: dict[str, object] = {
        "record_id": "check-failed",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "check",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-failed",
        "task_region_id": "region-prompt",
        "attempt_number": 1,
        "value": {
            "status": "failed",
            "classification": "failed",
            "command_id": "check",
            "command_text": "exit=1",
            "command": {"argv": ["false"]},
            "worktree_path": "/work",
            "base_snapshot_id": "baseline",
            "execution_id": "check-exec",
            "exit_code": 1,
            "duration_ms": 1,
            "stdout_tail": "",
            "stderr_tail": "exit=1",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
        "evaluated_record_ids": ["candidate-failed"],
    }
    gap: dict[str, object] = {
        "record_id": "gap-corrective",
        "record_kind": "output",
        "record_type": "classified_gap",
        "producer_node_id": "gap",
        "port": "classified_gap",
        "schema": "GapClassification",
        "value": {
            "milestone_kind": "verification_gap",
            "classification": "corrective_work_required",
            "source": "verification-failed + check-failed",
            "task_region_id": "region-prompt",
            "attempt_number": 1,
        },
    }
    return [
        (
            "output_record_accepted",
            _candidate_record(
                "candidate-failed",
                "candidate-source",
                "region-prompt",
                1,
            ),
        ),
        (
            "output_record_accepted",
            _verification_record(
                "failed",
                record_id="verification-failed",
                producer="verifier",
                candidate_id="candidate-failed",
            ),
        ),
        ("output_record_accepted", check),
        ("output_record_accepted", gap),
    ]


def _health_check_record() -> dict[str, object]:
    return {
        "record_id": "health-check-passed",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "health-check",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "runtime-health",
        "task_region_id": "region-healthy-retry",
        "attempt_number": 1,
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "runtime-health",
            "command_text": "runner health probe",
            "command": {"argv": ["true"]},
            "worktree_path": "/work",
            "base_snapshot_id": "baseline",
            "execution_id": "health-exec",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "healthy",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
        "evaluated_record_ids": [],
    }


def _candidate_record(
    candidate_id: str,
    producer: str,
    region_id: str,
    attempt_number: int,
    *,
    file_state_record_id: str | None = None,
) -> dict[str, object]:
    file_state_ids = [file_state_record_id] if file_state_record_id is not None else []
    return {
        "record_id": candidate_id,
        "record_kind": "output",
        "record_type": "candidate",
        "producer_node_id": producer,
        "port": "candidate",
        "schema": "ImplementationCandidate",
        "candidate_id": candidate_id,
        "task_region_id": region_id,
        "attempt_number": attempt_number,
        "file_state_record_id": file_state_record_id,
        "file_state_record_ids": file_state_ids,
        "value": {
            "summary": candidate_id,
            "file_state_record_id": file_state_record_id,
            "file_state_record_ids": file_state_ids,
        },
    }


def _file_state_record(
    record_id: str,
    producer: str,
    candidate_id: str,
    snapshot_id: str,
    base_snapshot_id: str,
    region_id: str,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "record_kind": "file_state",
        "record_type": "file_state",
        "producer_node_id": producer,
        "port": "file_state",
        "schema": "FileStateRecord",
        "snapshot_id": snapshot_id,
        "base_snapshot_id": base_snapshot_id,
        "task_region_id": region_id,
        "candidate_id": candidate_id,
        "paths": [],
        "verdict": "captured",
    }


def _candidate_snapshot_records(
    suffix: str,
    base_snapshot_id: str,
    *,
    attempt_number: int,
) -> list[dict[str, object]]:
    worker_id = f"worker-snapshot-{suffix}"
    candidate_id = f"candidate-{suffix}"
    file_state_id = f"file-state-{suffix}"
    return [
        _file_state_record(
            file_state_id,
            worker_id,
            candidate_id,
            f"snapshot-{suffix}",
            base_snapshot_id,
            "region-snapshots",
        ),
        _candidate_record(
            candidate_id,
            worker_id,
            "region-snapshots",
            attempt_number,
            file_state_record_id=file_state_id,
        ),
    ]


def _snapshot_scenario_facts() -> list[tuple[str, dict[str, object]]]:
    facts: list[tuple[str, dict[str, object]]] = []
    for attempt, suffix in enumerate(("one", "two", "three"), start=1):
        worker_id = f"worker-snapshot-{suffix}"
        verifier_id = f"verifier-snapshot-{suffix}"
        worker = {
            **_executable_worker(worker_id, "snapshots", access_mode="write"),
            "candidate_id": f"candidate-{suffix}",
            "attempt_number": attempt,
            "base_snapshot_selection": "run_baseline" if attempt == 1 else "accepted_region",
        }
        if attempt > 1:
            worker["base_snapshot_region_id"] = "region-snapshots"
        facts.extend(
            [
                ("node_created", worker),
                (
                    "node_created",
                    {
                        "node_id": verifier_id,
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "planned",
                        "task_region_id": "region-snapshots",
                        "attempt_number": attempt,
                        "base_snapshot_selection": "candidate_under_test",
                    },
                ),
                (
                    "edge_created",
                    {
                        "edge_id": f"edge-{worker_id}-{verifier_id}",
                        "from_node_id": worker_id,
                        "from_port": "candidate",
                        "to_node_id": verifier_id,
                        "to_port": "candidate_under_test",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "candidate",
                            "schema": "ImplementationCandidate",
                            "record_id": f"candidate-{suffix}",
                        },
                    },
                ),
            ]
        )
    facts.extend(
        [
            (
                "node_created",
                {
                    **_executable_worker("downstream-accepted-one", "downstream-one"),
                    "base_snapshot_selection": "accepted_region",
                    "base_snapshot_region_id": "region-snapshots",
                },
            ),
            (
                "node_created",
                {
                    **_executable_worker("downstream-rejected-two", "downstream-two"),
                    "base_snapshot_selection": "rejected_candidate",
                    "base_snapshot_candidate_id": "candidate-two",
                },
            ),
            (
                "node_created",
                {
                    **_executable_worker("downstream-accepted-three", "downstream-three"),
                    "base_snapshot_selection": "accepted_region",
                    "base_snapshot_region_id": "region-snapshots",
                },
            ),
        ]
    )
    return facts


def _final_gate_facts() -> list[tuple[str, dict[str, object]]]:
    facts: list[tuple[str, dict[str, object]]] = [
        (
            "node_created",
            {
                "node_id": "routine-snapshot",
                "kind": "artifact",
                "role": "routine_snapshot",
                "state": "completed",
                "outputs": [
                    {
                        "port": "semantic_schema_declaration",
                        "direction": "output",
                        "schema": "SemanticSchemaDeclaration",
                        "record_layers": ["graph_record"],
                        "required": False,
                    }
                ],
            },
        ),
        (
            "output_record_accepted",
            _semantic_schema_declaration("ordered-plan", "implementation_plan"),
        ),
        (
            "node_created",
            {"node_id": "planner-plan", "kind": "planner", "role": "planner", "state": "planned"},
        ),
        (
            "node_created",
            {
                **_executable_worker("worker-batch", "batch-1", access_mode="write"),
                "role": "implementer",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "region-batch-1",
                "candidate_id": "candidate-batch",
            },
        ),
        (
            "node_created",
            {
                "node_id": "check-batch",
                "kind": "check",
                "role": "batch_check",
                "state": "planned",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "region-batch-1",
                "base_snapshot_selection": "candidate_under_test",
                "command_definition": {
                    "id": "check-batch",
                    "argv": ["true"],
                    "must": True,
                },
            },
        ),
        (
            "node_created",
            {
                "node_id": "batch-verifier",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "semantic_stage": "effectful_batch",
                "declared_batch_id": "batch-1",
                "task_region_id": "region-batch-1",
                "candidate_id": "candidate-batch",
                "attempt_number": 1,
                "base_snapshot_selection": "candidate_under_test",
            },
        ),
        (
            "node_created",
            {
                "node_id": "final-acceptance",
                "kind": "check",
                "role": "acceptance_gate",
                "state": "planned",
                "semantic_stage": "final_acceptance",
                "command_binding": "dynamic_feature_acceptance",
            },
        ),
        (
            "node_created",
            {
                "node_id": "final-audit",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "semantic_stage": "final_audit",
            },
        ),
        (
            "node_created",
            {
                "node_id": "gate-final",
                "kind": "final_gate",
                "state": "ready",
                "declared_batch_ids": ["batch-1"],
            },
        ),
    ]
    facts.extend(_final_gate_topology())
    return facts


def _passed_check_record(*, base_snapshot_id: str, execution_id: str) -> dict[str, object]:
    return {
        "record_id": "check-result-batch",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "check-batch",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-batch",
        "task_region_id": "region-batch-1",
        "attempt_number": 1,
        "evaluated_record_ids": ["candidate-batch", "file-state-batch"],
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "batch-check",
            "command_text": "true",
            "command": {"argv": ["true"]},
            "worktree_path": "/work",
            "base_snapshot_id": base_snapshot_id,
            "execution_id": execution_id,
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
    }


def _passed_final_acceptance_record() -> dict[str, object]:
    return {
        "record_id": "final-acceptance-report",
        "record_kind": "output",
        "record_type": "check_result",
        "producer_node_id": "final-acceptance",
        "port": "check_result",
        "schema": "CheckResult",
        "candidate_id": "candidate-batch",
        "task_region_id": "region-batch-1",
        "attempt_number": 1,
        "candidate_record_ids": ["candidate-batch"],
        "file_state_record_ids": ["file-state-batch"],
        "verification_report_record_ids": ["batch-report"],
        "evaluated_record_ids": [
            "batch-report",
            "check-result-batch",
            "candidate-batch",
            "file-state-batch",
        ],
        "value": {
            "status": "passed",
            "classification": "passed",
            "command_id": "dynamic-feature-acceptance",
            "command_binding": "dynamic_feature_acceptance",
            "command_text": "true",
            "command": {"argv": ["true"]},
            "worktree_path": "/work",
            "base_snapshot_id": "snapshot-batch",
            "execution_snapshot_id": "snapshot-batch",
            "execution_snapshot_ref": "refs/orchestrator/snapshots/snapshot-batch",
            "execution_id": "execution-final-acceptance",
            "exit_code": 0,
            "duration_ms": 1,
            "stdout_tail": "",
            "stderr_tail": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timeout_seconds": 1.0,
            "environment_policy": {},
        },
    }


def _final_gate_topology() -> list[tuple[str, dict[str, object]]]:
    passed_report_selector: dict[str, object] = {
        "record_type": "verification_report",
        "schema": "VerificationReport",
        "outcome": "passed",
    }
    facts: list[tuple[str, dict[str, object]]] = [
        (
            "edge_created",
            {
                "edge_id": "edge-batch-acceptance",
                "from_node_id": "batch-verifier",
                "from_port": "verification_report",
                "to_node_id": "final-acceptance",
                "to_port": "verification_report_batch_1",
                "required": True,
                "accepted_record_selector": {
                    **passed_report_selector,
                    "record_id": "batch-report",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-plan-worker",
                "from_node_id": "planner-plan",
                "from_port": "semantic_artifact",
                "to_node_id": "worker-batch",
                "to_port": "semantic_artifact",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "semantic_artifact",
                    "schema": "SemanticArtifact",
                    "authority_status": "accepted",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-acceptance-audit",
                "from_node_id": "final-acceptance",
                "from_port": "check_result",
                "to_node_id": "final-audit",
                "to_port": "dynamic_feature_acceptance",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                    "record_id": "final-acceptance-report",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-acceptance-gate",
                "from_node_id": "final-acceptance",
                "from_port": "check_result",
                "to_node_id": "gate-final",
                "to_port": "dynamic_feature_acceptance",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                    "record_id": "final-acceptance-report",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-worker-check",
                "from_node_id": "worker-batch",
                "from_port": "candidate",
                "to_node_id": "check-batch",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                    "record_id": "candidate-batch",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-worker-verifier",
                "from_node_id": "worker-batch",
                "from_port": "candidate",
                "to_node_id": "batch-verifier",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "candidate",
                    "schema": "ImplementationCandidate",
                    "record_id": "candidate-batch",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-check-verifier",
                "from_node_id": "check-batch",
                "from_port": "check_result",
                "to_node_id": "batch-verifier",
                "to_port": "check_result_1",
                "required": True,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                    "record_id": "check-result-batch",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-check-verifier-citation",
                "from_node_id": "check-batch",
                "from_port": "check_result",
                "to_node_id": "batch-verifier",
                "to_port": "requirement_check_result_1",
                "required": False,
                "accepted_record_selector": {
                    "record_type": "check_result",
                    "schema": "CheckResult",
                    "status": "passed",
                    "record_id": "check-result-batch",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-batch-audit",
                "from_node_id": "batch-verifier",
                "from_port": "verification_report",
                "to_node_id": "final-audit",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {
                    **passed_report_selector,
                    "record_id": "batch-report",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-batch-gate",
                "from_node_id": "batch-verifier",
                "from_port": "verification_report",
                "to_node_id": "gate-final",
                "to_port": "batch_report",
                "required": True,
                "accepted_record_selector": {
                    **passed_report_selector,
                    "record_id": "batch-report",
                },
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-audit-gate",
                "from_node_id": "final-audit",
                "from_port": "verification_report",
                "to_node_id": "gate-final",
                "to_port": "final_audit",
                "required": True,
                "accepted_record_selector": {
                    **passed_report_selector,
                    "record_id": "audit-report",
                },
            },
        ),
    ]
    return facts
