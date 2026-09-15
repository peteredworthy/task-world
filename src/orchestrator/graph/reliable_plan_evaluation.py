"""Typed qualification and comparison artifacts for reliable-plan dogfood."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from hashlib import sha256
import json
from typing import Literal, Self, cast

from pydantic import BaseModel, Field, PrivateAttr, StrictInt, model_validator

from orchestrator.config import ModelProfile, RunStatus
from orchestrator.graph.decisions import (
    DECISION_COMPILER_CONTRACT_VERSION,
    DECISION_PLAN_SCHEMA_ID,
    DECISION_PLAN_SCHEMA_VERSION,
    decision_plan_schema_sha256,
)
from orchestrator.graph.models import RoutineSnapshotRecord, RunLifecycleState
from orchestrator.graph.projection_models import GraphProjection
from orchestrator.graph.projection_queries import (
    edges_view,
    environment_failures_view,
    leases_view,
    latest_routine_snapshot_record,
    node_attempts_view,
    node_payload_view,
    node_states_view,
    output_record_payloads_view,
    recovery_nodes_by_record_id_view,
    record_payloads_view,
    runtime_retry_counts_view,
    run_state,
    usage_metrics_view,
)
from orchestrator.graph.projections import iter_final_invariant_blockers


RELIABLE_PLAN_INCIDENT_ID = "fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"
RELIABLE_PLAN_SCENARIO_ID = "reliable-plan-fff4f6b7-v1"
RELIABLE_PLAN_RUNNER_ID = "sqlite-controller-product-path-v1"
RELIABLE_PLAN_RUNNER_VERSION = 1
REQUIRED_REGRESSION_SCENARIOS = frozenset(range(1, 11))
RELIABLE_PLAN_JOINED_CASE_IDS = frozenset(
    {
        "single-batch",
        "dependent-batches",
        "plan-amendment",
        "smoke",
        "correction",
        "blocked",
        "cancellation-restart",
        "defective-candidate",
        "defective-verifier",
        "compatibility",
    }
)


class ReliablePlanRuntimeLimits(BaseModel):
    """Optional hard limits for one reliable-plan planner node."""

    model_config = {"extra": "forbid"}

    max_rejected_plan_proposals_per_planner: StrictInt | None = Field(default=None, ge=1, le=100)
    max_planner_executions_per_node: StrictInt | None = Field(default=None, ge=1, le=100)


def canonical_reliable_plan_scenario_manifest(
    *, interaction_contract: Literal["legacy", "decision-v1"] = "legacy"
) -> "ReliablePlanScenarioManifest":
    """Return the server-owned incident manifest used to issue qualifications."""
    if interaction_contract == "decision-v1":
        return canonical_decision_v1_reliable_plan_scenario_manifest()
    return ReliablePlanScenarioManifest(
        contract_identity=ReliablePlanContractIdentity.for_interaction(interaction_contract),
        scenarios=(
            ReliablePlanScenarioDefinition(
                number=1,
                name="analysis-only discovery authority",
                product_path="planner patch validation and controller scheduling",
            ),
            ReliablePlanScenarioDefinition(
                number=2,
                name="accepted discovery and plan verification readiness",
                product_path="controller schedule_tick readiness",
            ),
            ReliablePlanScenarioDefinition(
                number=3,
                name="declared batch topology or accepted amendment",
                product_path="planner patch validation",
            ),
            ReliablePlanScenarioDefinition(
                number=4,
                name="bound requirement and evidence prompt hydration",
                product_path="runtime dispatch packet assembly",
            ),
            ReliablePlanScenarioDefinition(
                number=5,
                name="exact corrective grades and check results",
                product_path="corrective runtime dispatch packet assembly",
            ),
            ReliablePlanScenarioDefinition(
                number=6,
                name="semantic schema selector compatibility",
                product_path="controller callback acceptance",
            ),
            ReliablePlanScenarioDefinition(
                number=7,
                name="accepted snapshot base authority",
                product_path="controller lease grant",
            ),
            ReliablePlanScenarioDefinition(
                number=8,
                name="all batch verifications and final audit",
                product_path="controller final reconciliation",
            ),
            ReliablePlanScenarioDefinition(
                number=9,
                name="conclusive callback and lease recovery",
                product_path="controller agent_died recovery",
            ),
            ReliablePlanScenarioDefinition(
                number=10,
                name="operator semantic incompleteness visibility",
                product_path="durable node and region read models",
            ),
        ),
    )


def canonical_decision_v1_reliable_plan_scenario_manifest() -> "ReliablePlanScenarioManifest":
    """Describe the joined typed cases required for decision-v1 qualification."""
    joined = canonical_decision_v1_joined_case_manifest()
    return ReliablePlanScenarioManifest(
        contract_identity=joined.contract_identity,
        scenarios=tuple(
            ReliablePlanScenarioDefinition(
                number=number,
                name=case.name,
                product_path=case.product_path,
            )
            for number, case in enumerate(joined.cases, start=1)
        ),
    )


def _trimmed(value: str, *, name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{name} must be nonempty after trimming")
    return trimmed


class ReliablePlanContractIdentity(BaseModel):
    """The interaction/schema/compiler identity covered by qualification evidence."""

    model_config = {"extra": "forbid", "frozen": True}
    interaction_contract: Literal["legacy", "decision-v1"] = "legacy"
    answer_schema_id: str | None = None
    answer_schema_version: StrictInt | None = Field(default=None, ge=1)
    answer_schema_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    compiler_contract_version: StrictInt | None = Field(default=None, ge=1)

    @classmethod
    def for_interaction(
        cls, interaction_contract: Literal["legacy", "decision-v1"]
    ) -> "ReliablePlanContractIdentity":
        if interaction_contract == "legacy":
            return cls()
        return cls(
            interaction_contract=interaction_contract,
            answer_schema_id=DECISION_PLAN_SCHEMA_ID,
            answer_schema_version=DECISION_PLAN_SCHEMA_VERSION,
            answer_schema_sha256=decision_plan_schema_sha256(),
            compiler_contract_version=DECISION_COMPILER_CONTRACT_VERSION,
        )

    @model_validator(mode="after")
    def _validate_identity(self) -> "ReliablePlanContractIdentity":
        values = (
            self.answer_schema_id,
            self.answer_schema_version,
            self.answer_schema_sha256,
            self.compiler_contract_version,
        )
        if self.interaction_contract == "legacy":
            if any(value is not None for value in values):
                raise ValueError("legacy qualification cannot carry decision-v1 identity")
            return self
        expected = (
            DECISION_PLAN_SCHEMA_ID,
            DECISION_PLAN_SCHEMA_VERSION,
            decision_plan_schema_sha256(),
            DECISION_COMPILER_CONTRACT_VERSION,
        )
        if values != expected:
            raise ValueError(
                "qualification must bind the generated decision-v1 implementation-plan "
                "schema and compiler contract"
            )
        return self


class ReliablePlanScenarioDefinition(BaseModel):
    """One canonical numbered contract regression."""

    model_config = {"extra": "forbid", "frozen": True}
    number: int = Field(ge=1, le=10)
    name: str = Field(min_length=1)
    product_path: str = Field(min_length=1)

    @model_validator(mode="after")
    def _trim_text(self) -> Self:
        object.__setattr__(self, "name", _trimmed(self.name, name="scenario name"))
        object.__setattr__(
            self, "product_path", _trimmed(self.product_path, name="scenario product_path")
        )
        return self


class ReliablePlanScenarioManifest(BaseModel):
    """Canonical incident skeleton; executable results must match it exactly."""

    model_config = {"extra": "forbid", "frozen": True}
    incident_id: Literal["fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"] = RELIABLE_PLAN_INCIDENT_ID
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"] = RELIABLE_PLAN_SCENARIO_ID
    contract_identity: ReliablePlanContractIdentity = Field(
        default_factory=ReliablePlanContractIdentity
    )
    scenarios: tuple[ReliablePlanScenarioDefinition, ...]

    @model_validator(mode="after")
    def _complete_unique_manifest(self) -> Self:
        numbers = [scenario.number for scenario in self.scenarios]
        if len(numbers) != len(set(numbers)):
            raise ValueError("scenario manifest numbers must be unique")
        if set(numbers) != set(REQUIRED_REGRESSION_SCENARIOS):
            raise ValueError("scenario manifest must declare scenarios 1-10 exactly")
        return self


class ReliablePlanScenarioResult(BaseModel):
    """Evidence returned by one executable product-path scenario."""

    model_config = {"extra": "forbid", "frozen": True}
    number: int = Field(ge=1, le=10)
    name: str = Field(min_length=1)
    product_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    passed: bool
    product_path_passed: bool | None = None
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _trim_evidence(self) -> Self:
        if self.product_path_passed is not None and self.product_path_passed != self.passed:
            raise ValueError("product_path_passed must equal the observed pass status")
        object.__setattr__(self, "product_path_passed", self.passed)
        object.__setattr__(self, "name", _trimmed(self.name, name="scenario result name"))
        object.__setattr__(
            self,
            "product_path",
            _trimmed(self.product_path, name="scenario result product_path"),
        )
        object.__setattr__(self, "run_id", _trimmed(self.run_id, name="scenario run_id"))
        object.__setattr__(
            self,
            "evidence",
            tuple(_trimmed(item, name="scenario evidence") for item in self.evidence),
        )
        return self


class ReliablePlanScenarioObservation(BaseModel):
    """Controller-persisted facts observed after one scenario exercised production."""

    model_config = {"extra": "forbid", "frozen": True}
    number: int = Field(ge=1, le=10)
    name: str = Field(min_length=1)
    product_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    runner_id: Literal["sqlite-controller-product-path-v1"] = RELIABLE_PLAN_RUNNER_ID
    runner_version: Literal[1] = RELIABLE_PLAN_RUNNER_VERSION
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _canonical_text(self) -> Self:
        object.__setattr__(self, "name", _trimmed(self.name, name="scenario observation name"))
        object.__setattr__(
            self,
            "product_path",
            _trimmed(self.product_path, name="scenario observation product_path"),
        )
        object.__setattr__(
            self, "run_id", _trimmed(self.run_id, name="scenario observation run_id")
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(_trimmed(item, name="scenario observation evidence") for item in self.evidence),
        )
        return self

    @property
    def observation_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class ReliablePlanJoinedCaseDefinition(BaseModel):
    """One joined decision-v1 failure or recovery case."""

    model_config = {"extra": "forbid", "frozen": True}
    case_id: Literal[
        "single-batch",
        "dependent-batches",
        "plan-amendment",
        "smoke",
        "correction",
        "blocked",
        "cancellation-restart",
        "defective-candidate",
        "defective-verifier",
        "compatibility",
    ]
    name: str = Field(min_length=1)
    product_path: str = Field(min_length=1)
    expected_outcome: Literal["completed", "blocked", "cancelled", "compatibility"]

    @model_validator(mode="after")
    def _canonical_text(self) -> Self:
        object.__setattr__(self, "name", _trimmed(self.name, name="joined case name"))
        object.__setattr__(
            self,
            "product_path",
            _trimmed(self.product_path, name="joined case product_path"),
        )
        return self


class ReliablePlanJoinedCaseManifest(BaseModel):
    """Fixed server-owned joined failure/correction case set."""

    model_config = {"extra": "forbid", "frozen": True}
    contract_identity: ReliablePlanContractIdentity
    cases: tuple[ReliablePlanJoinedCaseDefinition, ...]

    @model_validator(mode="after")
    def _complete_case_set(self) -> Self:
        if self.contract_identity.interaction_contract != "decision-v1":
            raise ValueError("joined cases require decision-v1 contract identity")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(RELIABLE_PLAN_JOINED_CASE_IDS) or len(set(ids)) != len(ids):
            raise ValueError("joined case manifest must declare the fixed ten cases exactly")
        return self


class ReliablePlanJoinedCaseObservation(BaseModel):
    """Durable result of one joined case exercised through production graph code."""

    model_config = {"extra": "forbid", "frozen": True}
    case_id: Literal[
        "single-batch",
        "dependent-batches",
        "plan-amendment",
        "smoke",
        "correction",
        "blocked",
        "cancellation-restart",
        "defective-candidate",
        "defective-verifier",
        "compatibility",
    ]
    run_id: str = Field(min_length=1)
    outcome: Literal["completed", "blocked", "cancelled", "compatibility"]
    passed: bool
    false_acceptance: bool
    intervention_recorded: bool
    intentionally_unexecuted_node_ids: tuple[str, ...] = ()
    unfinished_node_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = Field(min_length=1)
    contract_identity: ReliablePlanContractIdentity
    finalized_execution_count: StrictInt = Field(ge=0)
    active_lease_count: StrictInt = Field(ge=0)
    suspended_lease_count: StrictInt = Field(ge=0)
    owned_process_count: StrictInt = Field(ge=0)
    pending_outbox_count: StrictInt = Field(ge=0)
    candidate_paths: tuple[str, ...]
    exact_candidate: bool
    clean_checkout: bool
    graph_state: RunLifecycleState | None
    workflow_status: RunStatus | None

    @model_validator(mode="after")
    def _validate_observation(self) -> Self:
        if self.false_acceptance and self.passed:
            raise ValueError("a false acceptance cannot be a passing joined case")
        if set(self.intentionally_unexecuted_node_ids) & set(self.unfinished_node_ids):
            raise ValueError("a node cannot be both isolated and unfinished")
        if self.contract_identity.interaction_contract != "decision-v1":
            raise ValueError("joined observations require decision-v1 contract identity")
        if self.passed and any(
            (
                self.active_lease_count,
                self.suspended_lease_count,
                self.owned_process_count,
                self.pending_outbox_count,
            )
        ):
            raise ValueError("passing joined evidence requires drained ownership and outbox")
        if self.outcome == "completed" and (
            self.graph_state != "completed"
            or self.workflow_status != RunStatus.COMPLETED
            or self.finalized_execution_count == 0
            or self.unfinished_node_ids
            or not self.exact_candidate
            or not self.clean_checkout
        ):
            raise ValueError("joined completion requires terminal runtime and exact clean product")
        object.__setattr__(
            self,
            "run_id",
            _trimmed(self.run_id, name="joined case run_id"),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(_trimmed(item, name="joined case evidence") for item in self.evidence),
        )
        return self


class ReliablePlanJoinedCaseQualification(BaseModel):
    """Qualification facts for the fixed joined decision-v1 case set."""

    model_config = {"extra": "forbid", "frozen": True}
    manifest: ReliablePlanJoinedCaseManifest
    observations: tuple[ReliablePlanJoinedCaseObservation, ...]

    @property
    def qualified(self) -> bool:
        return all(item.passed and not item.false_acceptance for item in self.observations)

    @model_validator(mode="after")
    def _observations_match_manifest(self) -> Self:
        by_id = {item.case_id: item for item in self.observations}
        if len(by_id) != len(self.observations):
            raise ValueError("joined case observations must be unique")
        declared = {case.case_id: case for case in self.manifest.cases}
        if set(by_id) != set(declared):
            raise ValueError("joined case observations must match the manifest exactly")
        for case_id, case in declared.items():
            observation = by_id[case_id]
            if observation.contract_identity != self.manifest.contract_identity:
                raise ValueError("joined observation contract identity differs from manifest")
            if observation.outcome != case.expected_outcome:
                raise ValueError(
                    f"joined case {case_id} outcome does not match its manifest expectation"
                )
        return self


def canonical_decision_v1_joined_case_manifest() -> ReliablePlanJoinedCaseManifest:
    """Return the fixed joined correction/failure cases for deterministic qualification."""
    identity = ReliablePlanContractIdentity.for_interaction("decision-v1")
    return ReliablePlanJoinedCaseManifest(
        contract_identity=identity,
        cases=(
            ReliablePlanJoinedCaseDefinition(
                case_id="single-batch",
                name="one complete typed batch",
                product_path="production create/start through decision-v1 final completion",
                expected_outcome="completed",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="dependent-batches",
                name="dependent typed batches",
                product_path="production dependency-ordered batches through final completion",
                expected_outcome="completed",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="plan-amendment",
                name="independently verified plan amendment",
                product_path="typed amendment, independent verification and execution",
                expected_outcome="completed",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="smoke",
                name="exact decision-v1 smoke product",
                product_path="typed lifecycle, exact stage3-smoke.txt oracle and public readback",
                expected_outcome="completed",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="correction",
                name="evidence-backed corrective cycle",
                product_path="joined candidate-check-verifier-correction path",
                expected_outcome="completed",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="blocked",
                name="bounded blocker and human intervention",
                product_path="typed blocker to durable blocked readback",
                expected_outcome="blocked",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="cancellation-restart",
                name="cancellation and restart fence",
                product_path="cancelled graph recovery readback",
                expected_outcome="cancelled",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="defective-candidate",
                name="defective candidate false-acceptance negative",
                product_path="failed mandatory evidence blocks final gate",
                expected_outcome="blocked",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="defective-verifier",
                name="defective verifier false-acceptance negative",
                product_path="failed independent verifier to evidence-backed escalation",
                expected_outcome="blocked",
            ),
            ReliablePlanJoinedCaseDefinition(
                case_id="compatibility",
                name="legacy and decision-v1 compatibility controls",
                product_path="trusted qualification identity round trip",
                expected_outcome="compatibility",
            ),
        ),
    )


class ReliablePlanQualificationReceipt(BaseModel):
    """Canonical controller-accepted receipt over all ten stored observations."""

    model_config = {"extra": "forbid", "frozen": True}
    receipt_record_id: str = Field(min_length=1)
    runner_id: Literal["sqlite-controller-product-path-v1"] = RELIABLE_PLAN_RUNNER_ID
    runner_version: Literal[1] = RELIABLE_PLAN_RUNNER_VERSION
    incident_id: Literal["fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"] = RELIABLE_PLAN_INCIDENT_ID
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"] = RELIABLE_PLAN_SCENARIO_ID
    contract_identity: ReliablePlanContractIdentity = Field(
        default_factory=ReliablePlanContractIdentity
    )
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observation_record_ids: tuple[str, ...] = Field(min_length=10, max_length=10)
    observation_hashes: tuple[str, ...] = Field(min_length=10, max_length=10)
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def reliable_plan_manifest_hash(manifest: ReliablePlanScenarioManifest) -> str:
    payload = manifest.model_dump(mode="json")
    # The legacy manifest hash is part of historical receipts.  The identity
    # was added after those receipts were issued, so preserve their exact
    # canonical bytes while including identity in every decision-v1 hash.
    if manifest.contract_identity.interaction_contract == "legacy":
        payload.pop("contract_identity", None)
    return _canonical_hash(payload)


ReliablePlanScenarioExecutor = Callable[
    [ReliablePlanScenarioDefinition], Awaitable[tuple[str, tuple[str, ...]]]
]


async def run_reliable_plan_scenarios(
    manifest: ReliablePlanScenarioManifest,
    execute: ReliablePlanScenarioExecutor,
) -> tuple[ReliablePlanScenarioResult, ...]:
    """Execute the canonical manifest; callers cannot supply pass booleans."""
    results: list[ReliablePlanScenarioResult] = []
    for scenario in manifest.scenarios:
        try:
            run_id, evidence = await execute(scenario)
        except Exception as exc:  # the result is evidence, not control flow
            results.append(
                ReliablePlanScenarioResult(
                    number=scenario.number,
                    name=scenario.name,
                    product_path=scenario.product_path,
                    run_id=f"failed-scenario-{scenario.number}",
                    passed=False,
                    evidence=(f"{type(exc).__name__}: {exc}",),
                )
            )
        else:
            results.append(
                ReliablePlanScenarioResult(
                    number=scenario.number,
                    name=scenario.name,
                    product_path=scenario.product_path,
                    run_id=run_id,
                    passed=True,
                    evidence=evidence,
                )
            )
    return tuple(results)


class ReliablePlanSkeletonQualification(BaseModel):
    """Qualification derived only from a runner's exact scenario results."""

    model_config = {"extra": "forbid", "frozen": True}
    runner_id: Literal["sqlite-controller-product-path-v1"] = RELIABLE_PLAN_RUNNER_ID
    manifest: ReliablePlanScenarioManifest
    results: tuple[ReliablePlanScenarioResult, ...]

    @classmethod
    def from_results(
        cls,
        manifest: ReliablePlanScenarioManifest,
        results: tuple[ReliablePlanScenarioResult, ...],
    ) -> Self:
        return cls(manifest=manifest, results=results)

    @property
    def passed_scenarios(self) -> frozenset[int]:
        return frozenset(result.number for result in self.results if result.passed)

    @property
    def qualified(self) -> bool:
        return self.passed_scenarios == REQUIRED_REGRESSION_SCENARIOS

    @model_validator(mode="after")
    def _results_match_manifest(self) -> Self:
        by_number = {result.number: result for result in self.results}
        if len(by_number) != len(self.results):
            raise ValueError("scenario result numbers must be unique")
        declared = {scenario.number: scenario for scenario in self.manifest.scenarios}
        if set(by_number) != set(declared):
            raise ValueError("scenario results must match the manifest exactly")
        for number, scenario in declared.items():
            result = by_number[number]
            if result.name != scenario.name or result.product_path != scenario.product_path:
                raise ValueError(f"scenario result {number} does not match its manifest entry")
        return self


class ReliablePlanQualificationAuthorityFacts(BaseModel):
    """Server-persisted facts derived from controller-accepted qualification records."""

    model_config = {"extra": "forbid", "frozen": True}
    qualification: ReliablePlanSkeletonQualification
    receipt: ReliablePlanQualificationReceipt

    @model_validator(mode="after")
    def _facts_agree(self) -> Self:
        if not self.qualification.qualified:
            raise ValueError("qualification authority facts require all ten passing scenarios")
        manifest = self.qualification.manifest
        receipt = self.receipt
        if (
            receipt.incident_id != manifest.incident_id
            or receipt.skeleton_id != manifest.skeleton_id
        ):
            raise ValueError("qualification authority incident or skeleton mismatch")
        if receipt.manifest_hash != reliable_plan_manifest_hash(manifest):
            raise ValueError("qualification authority manifest hash mismatch")
        if receipt.contract_identity != manifest.contract_identity:
            raise ValueError("qualification authority contract identity mismatch")
        return self


class ReliablePlanQualificationGrant(BaseModel):
    """Opaque, single-use server grant plus descriptive qualification evidence."""

    model_config = {"extra": "forbid", "frozen": True}
    reference: str = Field(pattern=r"^rpq_[A-Za-z0-9_-]{32,128}$")
    facts: ReliablePlanQualificationAuthorityFacts


class ReliablePlanModelAssignment(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    runner_type: Literal["openhands_local", "openhands_docker", "cli_subprocess", "codex_server"]
    model: str = Field(min_length=1)
    profile: ModelProfile

    @model_validator(mode="after")
    def _trim_model(self) -> Self:
        object.__setattr__(self, "model", _trimmed(self.model, name="model"))
        return self


class ReliablePlanEvaluationArm(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    arm_id: str = Field(min_length=1)
    planner: ReliablePlanModelAssignment
    discovery_worker: ReliablePlanModelAssignment
    implementation_worker: ReliablePlanModelAssignment
    correction_worker: ReliablePlanModelAssignment
    verifier: ReliablePlanModelAssignment
    successor_planner: ReliablePlanModelAssignment

    @model_validator(mode="after")
    def _trim_arm_id(self) -> Self:
        object.__setattr__(self, "arm_id", _trimmed(self.arm_id, name="arm_id"))
        return self


ReliablePlanEvaluationCaseId = Literal[
    "single-batch",
    "dependent-batches",
    "correction",
    "plan-amendment",
    "verifier-negative",
]
ReliablePlanEvaluationOutcome = Literal["completed", "blocked", "cancelled", "failed"]
ReliablePlanEvaluationIntervention = Literal[
    "none", "bounded-correction", "bounded-plan-amendment", "operator-escalation"
]
ReliablePlanEvaluationFailureClass = Literal[
    "provider_failure",
    "timeout",
    "cancellation",
    "validation_rejection",
    "candidate_check_failure",
    "verifier_failure",
    "environment_failure",
]


class ReliablePlanEvaluationBudget(BaseModel):
    """Explicit spend and execution limits for an evaluation unit."""

    model_config = {"extra": "forbid", "frozen": True}
    max_model_executions: StrictInt = Field(ge=0, le=1000)
    max_rejected_answers: StrictInt = Field(ge=0, le=2000)
    max_wall_seconds: StrictInt = Field(ge=1, le=86400)


class ReliablePlanEvaluationStopRules(BaseModel):
    """Fail-closed rules that are fixed before a model evaluation starts."""

    model_config = {"extra": "forbid", "frozen": True}
    stop_on_false_acceptance: Literal[True] = True
    stop_on_unexpected_outcome: Literal[True] = True
    stop_on_missing_evidence: Literal[True] = True
    no_automatic_retry: Literal[True] = True


class ReliablePlanEvaluationCaseDefinition(BaseModel):
    """One fixed representative case in the model-evaluation denominator."""

    model_config = {"extra": "forbid", "frozen": True}
    case_id: ReliablePlanEvaluationCaseId
    name: str = Field(min_length=1)
    product_path: str = Field(min_length=1)
    expected_outcome: ReliablePlanEvaluationOutcome
    allowed_interventions: tuple[ReliablePlanEvaluationIntervention, ...] = Field(min_length=1)
    false_acceptance_negative: bool = False
    expected_failure_classes: tuple[ReliablePlanEvaluationFailureClass, ...] = ()

    @model_validator(mode="after")
    def _validate_case(self) -> Self:
        object.__setattr__(self, "name", _trimmed(self.name, name="evaluation case name"))
        object.__setattr__(
            self,
            "product_path",
            _trimmed(self.product_path, name="evaluation case product_path"),
        )
        if self.expected_outcome == "completed" and "none" not in self.allowed_interventions:
            raise ValueError("completed evaluation cases must allow the no-intervention path")
        if self.false_acceptance_negative and self.expected_outcome == "completed":
            raise ValueError("false-acceptance negatives cannot expect completed work")
        if self.false_acceptance_negative and (
            not self.expected_failure_classes
            or not set(self.expected_failure_classes).issubset(
                {"validation_rejection", "candidate_check_failure", "verifier_failure"}
            )
        ):
            raise ValueError(
                "false-acceptance negatives require an explicit semantic failure oracle"
            )
        return self


class ReliablePlanEvaluationManifest(BaseModel):
    """Fixed, unexecuted model-evaluation card for the decision-v1 profile."""

    model_config = {"extra": "forbid", "frozen": True}
    manifest_id: Literal["reliable-plan-model-evaluation-v1"] = "reliable-plan-model-evaluation-v1"
    contract_identity: ReliablePlanContractIdentity
    arm: ReliablePlanEvaluationArm
    cases: tuple[ReliablePlanEvaluationCaseDefinition, ...]
    per_execution_budget: ReliablePlanEvaluationBudget
    per_case_budget: ReliablePlanEvaluationBudget
    total_budget: ReliablePlanEvaluationBudget
    stop_rules: ReliablePlanEvaluationStopRules
    operator_authorization_required: Literal[True] = True

    @property
    def assignment(self) -> ReliablePlanModelAssignment:
        """Return the primary successor assignment used by representative cases."""
        return self.arm.successor_planner

    @model_validator(mode="after")
    def _validate_manifest(self) -> Self:
        if self.contract_identity.interaction_contract != "decision-v1":
            raise ValueError("model evaluation requires decision-v1 contract identity")
        if (
            self.per_execution_budget.max_model_executions != 1
            or self.per_execution_budget.max_rejected_answers != 2
            or self.per_execution_budget.max_wall_seconds != 180
        ):
            raise ValueError("each phase permits one execution, two rejected answers and 180s")
        expected_ids = {
            "single-batch",
            "dependent-batches",
            "correction",
            "plan-amendment",
            "verifier-negative",
        }
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        if set(ids) != expected_ids:
            raise ValueError("evaluation manifest must declare the fixed five cases exactly")
        if self.per_case_budget != ReliablePlanEvaluationBudget(
            max_model_executions=16,
            max_rejected_answers=32,
            max_wall_seconds=2880,
        ):
            raise ValueError("evaluation manifest requires the fixed per-case budget")
        if self.total_budget != ReliablePlanEvaluationBudget(
            max_model_executions=80,
            max_rejected_answers=160,
            max_wall_seconds=14400,
        ):
            raise ValueError("evaluation manifest requires the fixed total budget")
        if self.stop_rules.no_automatic_retry is not True:
            raise ValueError("evaluation manifest must disable automatic retry")
        return self


class ReliablePlanEvaluationAttempt(BaseModel):
    """One actual model attempt, including a failed attempt when it has no usage."""

    model_config = {"extra": "forbid", "frozen": True}
    attempt_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    status: ReliablePlanEvaluationOutcome
    model_execution_count: StrictInt = Field(ge=0, le=1000)
    rejected_answer_count: StrictInt = Field(ge=0, le=2000)
    latency_ms: StrictInt | None = Field(default=None, ge=0)
    usage: ReliablePlanUsageMetrics | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    failure_class: ReliablePlanEvaluationFailureClass | None = None

    @model_validator(mode="after")
    def _validate_attempt(self) -> Self:
        object.__setattr__(self, "attempt_id", _trimmed(self.attempt_id, name="attempt_id"))
        object.__setattr__(self, "node_id", _trimmed(self.node_id, name="node_id"))
        object.__setattr__(self, "execution_id", _trimmed(self.execution_id, name="execution_id"))
        if self.status == "failed" and self.failure_class is None:
            raise ValueError("failed evaluation attempts require failure_class")
        if self.status != "failed" and self.failure_class is not None:
            raise ValueError("only failed evaluation attempts may carry failure_class")
        return self


class ReliablePlanEvaluationCaseResult(BaseModel):
    """Observed product outcome for one manifest case."""

    model_config = {"extra": "forbid", "frozen": True}
    case_id: ReliablePlanEvaluationCaseId
    run_id: str = Field(min_length=1)
    outcome: ReliablePlanEvaluationOutcome
    false_acceptance: bool
    intervention_count: StrictInt = Field(ge=0)
    interventions: tuple[ReliablePlanEvaluationIntervention, ...] = ()
    attempts: tuple[ReliablePlanEvaluationAttempt, ...] = ()
    evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _canonical_result(self) -> Self:
        object.__setattr__(self, "run_id", _trimmed(self.run_id, name="evaluation run_id"))
        object.__setattr__(
            self,
            "evidence",
            tuple(_trimmed(item, name="evaluation evidence") for item in self.evidence),
        )
        if len({attempt.attempt_id for attempt in self.attempts}) != len(self.attempts):
            raise ValueError("evaluation attempt IDs must be unique within a case")
        if len(self.interventions) != self.intervention_count:
            raise ValueError("intervention_count must match interventions")
        if "none" in self.interventions and self.intervention_count != 0:
            raise ValueError("none cannot be combined with an intervention")
        return self


class ReliablePlanEvaluationMetrics(BaseModel):
    """Count-first aggregate; unavailable telemetry is deliberately represented by None."""

    model_config = {"extra": "forbid", "frozen": True}
    case_count: StrictInt = Field(ge=0)
    denominator: StrictInt = Field(ge=0)
    correct_completion_count: StrictInt = Field(ge=0)
    correct_completion_denominator: StrictInt = Field(ge=0)
    false_acceptance_count: StrictInt = Field(ge=0)
    false_acceptance_denominator: StrictInt = Field(ge=0)
    bounded_failure_count: StrictInt = Field(ge=0)
    bounded_failure_denominator: StrictInt = Field(ge=0)
    intervention_count: StrictInt = Field(ge=0)
    intervention_denominator: StrictInt = Field(ge=0)
    intervention_rate: float | None = Field(default=None, ge=0, le=1)
    model_execution_count: StrictInt = Field(ge=0)
    failed_attempt_count: StrictInt = Field(ge=0)
    rejected_answer_count: StrictInt = Field(ge=0)
    latency_ms_total: StrictInt | None = Field(default=None, ge=0)
    latency_denominator: StrictInt = Field(ge=0)
    total_tokens: StrictInt | None = Field(default=None, ge=0)
    total_actions: StrictInt | None = Field(default=None, ge=0)
    total_duration_ms: StrictInt | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)


class ReliablePlanEvaluationReport(BaseModel):
    """Fixed-denominator report derived from observed case and attempt carriers."""

    model_config = {"extra": "forbid", "frozen": True}
    manifest: ReliablePlanEvaluationManifest
    results: tuple[ReliablePlanEvaluationCaseResult, ...]
    metrics: ReliablePlanEvaluationMetrics | None = None
    violations: tuple[str, ...] = ()
    passed: bool = False

    @classmethod
    def from_results(
        cls,
        manifest: ReliablePlanEvaluationManifest,
        results: tuple[ReliablePlanEvaluationCaseResult, ...],
    ) -> Self:
        return cls(manifest=manifest, results=results)

    @model_validator(mode="after")
    def _derive_report(self) -> Self:
        declared = {case.case_id: case for case in self.manifest.cases}
        by_id = {result.case_id: result for result in self.results}
        if len(by_id) != len(self.results):
            raise ValueError("evaluation case results must be unique")
        unknown_ids = set(by_id) - set(declared)
        if unknown_ids:
            raise ValueError("evaluation results contain cases outside the manifest")
        violations = [
            f"missing result for case {case.case_id}"
            for case in self.manifest.cases
            if case.case_id not in by_id
        ]
        seen_run_ids: set[str] = set()
        for result in self.results:
            if result.run_id in seen_run_ids:
                violations.append(f"run ID {result.run_id} is reused across cases")
            seen_run_ids.add(result.run_id)
        for case_id, result in by_id.items():
            case = declared[case_id]
            if not set(result.interventions).issubset(case.allowed_interventions):
                violations.append(f"case {case_id} contains an unallowed intervention")
            if result.outcome != case.expected_outcome:
                violations.append(f"case {case_id} produced an unexpected outcome")
            if result.false_acceptance:
                violations.append(f"case {case_id} produced a false acceptance")
            if not _exercises_expected_failure(case, result):
                violations.append(f"case {case_id} did not exercise its required failure")
            if not result.evidence:
                violations.append(f"case {case_id} is missing required evidence")
            if result.outcome == "completed" and not any(
                attempt.status == "completed" for attempt in result.attempts
            ):
                violations.append(f"case {case_id} has no completed attempt")
            if result.outcome == "completed" and not any(
                attempt.model_execution_count > 0 for attempt in result.attempts
            ):
                violations.append(f"case {case_id} has no recorded model execution")

        violations.extend(_validate_evaluation_budgets(self.manifest, self.results))

        computed = _evaluation_metrics(self.manifest, self.results)
        if self.metrics is not None and self.metrics != computed:
            raise ValueError("evaluation metrics must match observed case results")
        object.__setattr__(self, "metrics", computed)
        object.__setattr__(self, "violations", tuple(violations))
        object.__setattr__(self, "passed", not violations)
        return self


ReliablePlanAssignmentRole = Literal[
    "planner",
    "discovery_worker",
    "implementation_worker",
    "correction_worker",
    "verifier",
    "successor_planner",
]


class ReliablePlanAssignmentCarrier(BaseModel):
    """Sealed, redundant execution assignments propagated to reliable-plan nodes."""

    model_config = {"extra": "forbid", "frozen": True}
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"]
    arm: ReliablePlanEvaluationArm
    selected_runner_type: Literal[
        "openhands_local", "openhands_docker", "cli_subprocess", "codex_server"
    ]

    @model_validator(mode="after")
    def _single_selected_runner(self) -> Self:
        runner_types = {
            assignment.runner_type
            for assignment in (
                self.arm.planner,
                self.arm.discovery_worker,
                self.arm.implementation_worker,
                self.arm.correction_worker,
                self.arm.verifier,
                self.arm.successor_planner,
            )
        }
        if runner_types != {self.selected_runner_type}:
            raise ValueError(
                "reliable-plan assignments must all use the selected runner "
                f"{self.selected_runner_type}"
            )
        return self

    def assignment_for(self, role: ReliablePlanAssignmentRole) -> ReliablePlanModelAssignment:
        return getattr(self.arm, role)


def reliable_plan_assignment_carrier(
    *,
    skeleton_id: str,
    arm: object,
    selected_runner_type: str,
) -> ReliablePlanAssignmentCarrier:
    """Validate the complete arm and bind it to the one selected runner."""

    return ReliablePlanAssignmentCarrier.model_validate(
        {
            "skeleton_id": skeleton_id,
            "arm": arm,
            "selected_runner_type": selected_runner_type,
        }
    )


class ReliablePlanEvaluationConfig(BaseModel):
    """Two-arm dogfood configuration.

    Public JSON is descriptive and can never enable the one-horizon gate.  The
    controller-backed authorization function below sets the private capability
    only after validating a durable receipt and each observation it covers.
    """

    model_config = {"extra": "forbid"}
    incident_id: Literal["fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"] = RELIABLE_PLAN_INCIDENT_ID
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"] = RELIABLE_PLAN_SCENARIO_ID
    scenario_manifest: ReliablePlanScenarioManifest
    luna_arm: ReliablePlanEvaluationArm
    alternate_arm: ReliablePlanEvaluationArm
    qualification: ReliablePlanSkeletonQualification | None = None
    enable_luna_one_horizon_planning: bool = False
    _qualification_authority: object | None = PrivateAttr(default=None)
    _qualification_receipt: ReliablePlanQualificationReceipt | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _validate_arms_and_gate(self) -> Self:
        if self.scenario_manifest.skeleton_id != self.skeleton_id:
            raise ValueError("scenario manifest does not match skeleton_id")
        if self.luna_arm.arm_id == self.alternate_arm.arm_id:
            raise ValueError("luna and alternate arm IDs must differ")
        if self.luna_arm == self.alternate_arm:
            raise ValueError("alternate arm assignments must differ from Luna")
        if self.qualification is not None and self.qualification.manifest != self.scenario_manifest:
            raise ValueError("qualification manifest does not match evaluation manifest")
        if self.enable_luna_one_horizon_planning:
            raise ValueError(
                "Luna one-horizon planning requires a controller-accepted "
                "qualification receipt; public JSON cannot enable it"
            )
        return self

    @property
    def one_horizon_authorized(self) -> bool:
        return (
            self.enable_luna_one_horizon_planning
            and self._qualification_authority is _ONE_HORIZON_AUTHORITY
            and self._qualification_receipt is not None
        )

    @property
    def accepted_qualification_receipt(self) -> ReliablePlanQualificationReceipt | None:
        return self._qualification_receipt

    def authorize_from_controller_receipt(
        self,
        qualification: ReliablePlanSkeletonQualification,
        receipt: ReliablePlanQualificationReceipt,
        authority: object,
    ) -> Self:
        if authority is not _ONE_HORIZON_AUTHORITY:
            raise ValueError("invalid reliable-plan qualification authority")
        authorized = self.model_copy(
            update={
                "qualification": qualification,
                "enable_luna_one_horizon_planning": True,
            }
        )
        authorized._qualification_authority = authority
        authorized._qualification_receipt = receipt
        return authorized


_ONE_HORIZON_AUTHORITY = object()


def authorize_reliable_plan_one_horizon(
    config: ReliablePlanEvaluationConfig,
    projection: GraphProjection,
    accepted_receipt_record_id: str,
) -> ReliablePlanEvaluationConfig:
    """Authorize one-horizon planning from exact durable controller facts.

    Caller-supplied ``ReliablePlanScenarioResult`` and qualification JSON are
    deliberately ignored.  Every observation and the receipt must be present
    in the accepted record projection and all runner, version, incident,
    scenario, manifest, and evidence hashes must agree exactly.
    """

    qualification, receipt = qualification_from_accepted_records(
        config.scenario_manifest,
        projection,
        accepted_receipt_record_id,
    )
    return config.authorize_from_controller_receipt(
        qualification,
        receipt,
        _ONE_HORIZON_AUTHORITY,
    )


def require_reliable_plan_one_horizon_authorization(
    config: ReliablePlanEvaluationConfig,
) -> ReliablePlanQualificationReceipt:
    receipt = config.accepted_qualification_receipt
    if not config.one_horizon_authorized or receipt is None:
        raise ValueError(
            "Luna one-horizon planning requires a controller-accepted qualification receipt"
        )
    return receipt


def serialize_authorized_reliable_plan_run_config(
    config: ReliablePlanEvaluationConfig,
    arm: ReliablePlanEvaluationArm,
) -> dict[str, object]:
    """Build the ordinary run configuration after trusted preflight.

    The private controller-backed capability deliberately does not cross the
    JSON boundary.  In particular, the serialized run configuration contains
    no enable boolean, qualification artifact, or receipt fields that a public
    caller could copy to self-authorize.  Calling this function is the launch
    gate: it succeeds only while the in-process config still carries the
    authority established by :func:`authorize_reliable_plan_one_horizon`.
    """

    require_reliable_plan_one_horizon_authorization(config)
    return {
        "reliable_plan_skeleton_id": config.skeleton_id,
        "reliable_plan_model_assignments": arm.model_dump(mode="json"),
    }


def qualification_from_accepted_records(
    manifest: ReliablePlanScenarioManifest,
    projection: GraphProjection,
    accepted_receipt_record_id: str,
) -> tuple[ReliablePlanSkeletonQualification, ReliablePlanQualificationReceipt]:
    records = record_payloads_view(projection)
    receipt_record = records.get(accepted_receipt_record_id)
    receipt_content = _reliable_plan_artifact_content(
        receipt_record,
        expected_role="reliable_plan_qualification_receipt",
    )
    receipt = ReliablePlanQualificationReceipt.model_validate(receipt_content)
    if receipt.receipt_record_id != accepted_receipt_record_id:
        raise ValueError("qualification receipt record identity mismatch")
    if receipt.incident_id != manifest.incident_id or receipt.skeleton_id != manifest.skeleton_id:
        raise ValueError("qualification receipt incident or skeleton mismatch")
    if receipt.contract_identity != manifest.contract_identity:
        raise ValueError("qualification receipt contract identity mismatch")
    if receipt.manifest_hash != reliable_plan_manifest_hash(manifest):
        raise ValueError("qualification receipt manifest hash mismatch")

    declared = {item.number: item for item in manifest.scenarios}
    observations: list[ReliablePlanScenarioObservation] = []
    observed_hashes: list[str] = []
    for record_id in receipt.observation_record_ids:
        content = _reliable_plan_artifact_content(
            records.get(record_id),
            expected_role="reliable_plan_scenario_observation",
        )
        observation = ReliablePlanScenarioObservation.model_validate(content)
        expected = declared.get(observation.number)
        if expected is None or (
            observation.name != expected.name or observation.product_path != expected.product_path
        ):
            raise ValueError(f"qualification observation {observation.number} mismatches manifest")
        observations.append(observation)
        observed_hashes.append(observation.observation_hash)
    if frozenset(item.number for item in observations) != REQUIRED_REGRESSION_SCENARIOS:
        raise ValueError("qualification receipt must cover scenarios 1-10 exactly")
    if tuple(observed_hashes) != receipt.observation_hashes:
        raise ValueError("qualification receipt observation hashes mismatch")
    if receipt.evidence_hash != _canonical_hash(observed_hashes):
        raise ValueError("qualification receipt evidence hash mismatch")

    by_number = {item.number: item for item in observations}
    results = tuple(
        ReliablePlanScenarioResult(
            number=scenario.number,
            name=scenario.name,
            product_path=scenario.product_path,
            run_id=by_number[scenario.number].run_id,
            passed=True,
            evidence=by_number[scenario.number].evidence,
        )
        for scenario in manifest.scenarios
    )
    return ReliablePlanSkeletonQualification.from_results(manifest, results), receipt


def _reliable_plan_artifact_content(
    record: dict[str, object] | None,
    *,
    expected_role: str,
) -> dict[str, object]:
    if record is None:
        raise ValueError(f"missing accepted {expected_role} record")
    if (
        record.get("record_type") != "semantic_artifact"
        or record.get("schema") != "SemanticArtifact"
    ):
        raise ValueError(f"{expected_role} must be an accepted SemanticArtifact")
    raw_value = record.get("value")
    if not isinstance(raw_value, dict):
        raise ValueError(f"{expected_role} value is missing")
    value = cast(dict[str, object], raw_value)
    if (
        value.get("semantic_role") != expected_role
        or value.get("schema_id") != "reliable-plan-qualification"
        or value.get("schema_version") != 1
        or value.get("authority_status", "accepted") != "accepted"
        or value.get("validation_status", "validated") != "validated"
    ):
        raise ValueError(f"{expected_role} authority or schema mismatch")
    raw_content = value.get("content")
    if not isinstance(raw_content, dict):
        raise ValueError(f"{expected_role} content is missing")
    return cast(dict[str, object], raw_content)


class ReliablePlanCorrectnessMetrics(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    passed: bool
    terminal_state: str | None
    final_blocker_count: int = Field(ge=0)
    failed_node_count: int = Field(ge=0)


class ReliablePlanGraphShapeMetrics(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    batch_ids: tuple[str, ...] = ()
    planning_horizons: tuple[int, ...] = ()


class ReliablePlanUsageMetrics(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    total_tokens: int = Field(ge=0)
    total_actions: int = Field(ge=0)
    total_duration_ms: int = Field(ge=0)
    tokens_by_node_kind: dict[str, int] = Field(default_factory=dict)
    actions_by_node_kind: dict[str, int] = Field(default_factory=dict)
    duration_ms_by_node_kind: dict[str, int] = Field(default_factory=dict)


ReliablePlanEvaluationAttempt.model_rebuild()


def canonical_decision_v1_model_evaluation_manifest() -> ReliablePlanEvaluationManifest:
    """Return the fixed, unexecuted representative model-evaluation card."""
    return ReliablePlanEvaluationManifest(
        contract_identity=ReliablePlanContractIdentity.for_interaction("decision-v1"),
        arm=ReliablePlanEvaluationArm(
            arm_id="luna-bounded-workers",
            planner=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-sol", profile=ModelProfile.ARCHITECT
            ),
            discovery_worker=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-luna", profile=ModelProfile.SUMMARIZER
            ),
            implementation_worker=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-luna", profile=ModelProfile.CODER
            ),
            correction_worker=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-luna", profile=ModelProfile.CODER
            ),
            verifier=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-sol", profile=ModelProfile.CODER
            ),
            successor_planner=ReliablePlanModelAssignment(
                runner_type="codex_server", model="gpt-5.6-luna", profile=ModelProfile.ARCHITECT
            ),
        ),
        cases=(
            ReliablePlanEvaluationCaseDefinition(
                case_id="single-batch",
                name="single-batch successor completion",
                product_path="joined one-batch decision and finalization",
                expected_outcome="completed",
                allowed_interventions=("none",),
            ),
            ReliablePlanEvaluationCaseDefinition(
                case_id="dependent-batches",
                name="dependent multi-batch completion",
                product_path="joined dependency-ordered successor horizons",
                expected_outcome="completed",
                allowed_interventions=("none",),
            ),
            ReliablePlanEvaluationCaseDefinition(
                case_id="correction",
                name="evidence-backed corrective completion",
                product_path="joined failed-check correction and finalization",
                expected_outcome="completed",
                allowed_interventions=("bounded-correction", "none"),
            ),
            ReliablePlanEvaluationCaseDefinition(
                case_id="plan-amendment",
                name="independently verified plan amendment",
                product_path="joined amendment verification and successor execution",
                expected_outcome="completed",
                allowed_interventions=("bounded-plan-amendment", "none"),
            ),
            ReliablePlanEvaluationCaseDefinition(
                case_id="verifier-negative",
                name="verifier negative must fail closed",
                product_path="joined defective candidate and verifier negative",
                expected_outcome="blocked",
                allowed_interventions=("operator-escalation",),
                false_acceptance_negative=True,
                expected_failure_classes=(
                    "verifier_failure",
                    "validation_rejection",
                    "candidate_check_failure",
                ),
            ),
        ),
        per_execution_budget=ReliablePlanEvaluationBudget(
            max_model_executions=1,
            max_rejected_answers=2,
            max_wall_seconds=180,
        ),
        per_case_budget=ReliablePlanEvaluationBudget(
            max_model_executions=16,
            max_rejected_answers=32,
            max_wall_seconds=2880,
        ),
        total_budget=ReliablePlanEvaluationBudget(
            max_model_executions=80,
            max_rejected_answers=160,
            max_wall_seconds=14400,
        ),
        stop_rules=ReliablePlanEvaluationStopRules(),
    )


canonical_reliable_plan_model_evaluation_manifest = canonical_decision_v1_model_evaluation_manifest


def _optional_sum(values: Sequence[object]) -> int | float | None:
    if not values or any(value is None for value in values):
        return None
    return sum(cast(list[int | float], list(values)))


def _exercises_expected_failure(
    case: ReliablePlanEvaluationCaseDefinition,
    result: ReliablePlanEvaluationCaseResult,
) -> bool:
    if not case.expected_failure_classes:
        return True
    if not result.attempts:
        return False
    final = result.attempts[-1]
    return final.failure_class in case.expected_failure_classes and any(
        attempt.node_id == final.node_id
        and attempt.execution_id == final.execution_id
        and attempt.model_execution_count == 1
        for attempt in result.attempts
    )


def _evaluation_metrics(
    manifest: ReliablePlanEvaluationManifest,
    results: tuple[ReliablePlanEvaluationCaseResult, ...],
) -> ReliablePlanEvaluationMetrics:
    declared = {case.case_id: case for case in manifest.cases}
    correct = [
        result
        for result in results
        if result.outcome == declared[result.case_id].expected_outcome
        and not result.false_acceptance
        and result.evidence
        and any(attempt.model_execution_count == 1 for attempt in result.attempts)
        and _exercises_expected_failure(declared[result.case_id], result)
        and not _validate_evaluation_budgets(manifest, (result,))
    ]
    completion_results = [
        result for result in results if declared[result.case_id].expected_outcome == "completed"
    ]
    failure_results = [
        result for result in results if declared[result.case_id].expected_outcome != "completed"
    ]
    attempts = [attempt for result in results for attempt in result.attempts]
    latencies = [attempt.latency_ms for attempt in attempts]
    usages = [attempt.usage for attempt in attempts]
    token_values = [usage.total_tokens if usage is not None else None for usage in usages]
    action_values = [usage.total_actions if usage is not None else None for usage in usages]
    duration_values = [usage.total_duration_ms if usage is not None else None for usage in usages]
    cost_values = [attempt.cost_usd for attempt in attempts]
    latency_total = _optional_sum(latencies)
    token_total = _optional_sum(token_values)
    action_total = _optional_sum(action_values)
    duration_total = _optional_sum(duration_values)
    cost_total = _optional_sum(cost_values)
    return ReliablePlanEvaluationMetrics(
        case_count=len(results),
        denominator=len(manifest.cases),
        correct_completion_count=sum(result in correct for result in completion_results),
        correct_completion_denominator=sum(
            case.expected_outcome == "completed" for case in manifest.cases
        ),
        false_acceptance_count=sum(result.false_acceptance for result in results),
        false_acceptance_denominator=len(manifest.cases),
        bounded_failure_count=sum(result in correct for result in failure_results),
        bounded_failure_denominator=sum(
            case.expected_outcome != "completed" for case in manifest.cases
        ),
        intervention_count=sum(result.intervention_count for result in results),
        intervention_denominator=len(manifest.cases),
        intervention_rate=(
            sum(result.intervention_count > 0 for result in results) / len(manifest.cases)
        )
        if len(results) == len(manifest.cases)
        else None,
        model_execution_count=sum(attempt.model_execution_count for attempt in attempts),
        failed_attempt_count=sum(attempt.status == "failed" for attempt in attempts),
        rejected_answer_count=sum(attempt.rejected_answer_count for attempt in attempts),
        latency_ms_total=cast(int | None, latency_total),
        latency_denominator=sum(latency is not None for latency in latencies),
        total_tokens=cast(int | None, token_total),
        total_actions=cast(int | None, action_total),
        total_duration_ms=cast(int | None, duration_total),
        total_cost_usd=cast(float | None, cost_total),
    )


def _validate_evaluation_budgets(
    manifest: ReliablePlanEvaluationManifest,
    results: tuple[ReliablePlanEvaluationCaseResult, ...],
) -> tuple[str, ...]:
    violations: list[str] = []
    total_executions = 0
    total_rejected_answers = 0
    total_wall_ms = 0
    total_wall_known = True
    for result in results:
        executions = sum(attempt.model_execution_count for attempt in result.attempts)
        rejected_answers = sum(attempt.rejected_answer_count for attempt in result.attempts)
        measured_attempts = [
            attempt for attempt in result.attempts if attempt.model_execution_count > 0
        ]
        latencies = [attempt.latency_ms for attempt in measured_attempts]
        execution_groups: dict[tuple[str, str], list[ReliablePlanEvaluationAttempt]] = {}
        node_groups: dict[str, list[ReliablePlanEvaluationAttempt]] = {}
        for attempt in result.attempts:
            execution_groups.setdefault((attempt.node_id, attempt.execution_id), []).append(attempt)
            node_groups.setdefault(attempt.node_id, []).append(attempt)

        for (node_id, execution_id), attempts in execution_groups.items():
            prefix = f"case {result.case_id} execution {node_id}/{execution_id}"
            group_executions = sum(attempt.model_execution_count for attempt in attempts)
            group_rejected_answers = sum(attempt.rejected_answer_count for attempt in attempts)
            group_latencies = [
                attempt.latency_ms for attempt in attempts if attempt.model_execution_count > 0
            ]
            received_answer = any(
                attempt.rejected_answer_count > 0 or attempt.status == "completed"
                for attempt in attempts
            )
            if received_answer and group_executions == 0:
                violations.append(f"{prefix} has no model execution")
            if group_executions > manifest.per_execution_budget.max_model_executions:
                violations.append(f"{prefix} exceeded model-execution budget")
            if group_rejected_answers > manifest.per_execution_budget.max_rejected_answers:
                violations.append(f"{prefix} exceeded rejected-answer budget")
            if any(latency is None for latency in group_latencies):
                violations.append(f"{prefix} has unknown wall time")
            elif sum(cast(list[int], group_latencies)) > (
                manifest.per_execution_budget.max_wall_seconds * 1000
            ):
                violations.append(f"{prefix} exceeded wall-time budget")

        for node_id, attempts in node_groups.items():
            prefix = f"case {result.case_id} node {node_id}"
            node_executions = sum(attempt.model_execution_count for attempt in attempts)
            node_rejected_answers = sum(attempt.rejected_answer_count for attempt in attempts)
            node_latencies = [
                attempt.latency_ms for attempt in attempts if attempt.model_execution_count > 0
            ]
            if node_executions > manifest.per_execution_budget.max_model_executions:
                violations.append(f"{prefix} exceeded model-execution budget")
            if node_rejected_answers > manifest.per_execution_budget.max_rejected_answers:
                violations.append(f"{prefix} exceeded rejected-answer budget")
            if node_latencies and all(latency is not None for latency in node_latencies):
                if sum(cast(list[int], node_latencies)) > (
                    manifest.per_execution_budget.max_wall_seconds * 1000
                ):
                    violations.append(f"{prefix} exceeded wall-time budget")

        if executions > manifest.per_case_budget.max_model_executions:
            violations.append(f"case {result.case_id} exceeded model-execution budget")
        if rejected_answers > manifest.per_case_budget.max_rejected_answers:
            violations.append(f"case {result.case_id} exceeded rejected-answer budget")
        if any(latency is None for latency in latencies):
            total_wall_known = False
        else:
            case_wall_ms = sum(cast(list[int], latencies))
            total_wall_ms += case_wall_ms
            if case_wall_ms > manifest.per_case_budget.max_wall_seconds * 1000:
                violations.append(f"case {result.case_id} exceeded wall-time budget")
        total_executions += executions
        total_rejected_answers += rejected_answers
    if total_executions > manifest.total_budget.max_model_executions:
        violations.append("evaluation exceeded total model-execution budget")
    if total_rejected_answers > manifest.total_budget.max_rejected_answers:
        violations.append("evaluation exceeded total rejected-answer budget")
    if total_wall_known and total_wall_ms > manifest.total_budget.max_wall_seconds * 1000:
        violations.append("evaluation exceeded total wall-time budget")
    return tuple(violations)


class ReliablePlanRecoveryMetrics(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    infrastructure_failure_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    recovery_node_count: int = Field(ge=0)
    revoked_lease_count: int = Field(ge=0)
    active_lease_count: int = Field(ge=0)


class ReliablePlanEvaluationResult(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    run_id: str = Field(min_length=1)
    arm_id: str = Field(min_length=1)
    evidence_status: Literal["complete", "blocked"]
    blocked_reason: str | None = None
    baseline_kind: Literal["dynamic_graph", "legacy_plan_then_execute"]
    correctness: ReliablePlanCorrectnessMetrics
    revision_count: int = Field(ge=0)
    graph_shape: ReliablePlanGraphShapeMetrics
    usage: ReliablePlanUsageMetrics
    recovery: ReliablePlanRecoveryMetrics
    model_profiles: ReliablePlanEvaluationArm
    contract_identity: ReliablePlanContractIdentity = Field(
        default_factory=ReliablePlanContractIdentity
    )

    @model_validator(mode="after")
    def _validate_identity_and_status(self) -> Self:
        object.__setattr__(self, "run_id", _trimmed(self.run_id, name="run_id"))
        object.__setattr__(self, "arm_id", _trimmed(self.arm_id, name="result arm_id"))
        if self.arm_id != self.model_profiles.arm_id:
            raise ValueError("result arm_id must match model_profiles.arm_id")
        if self.evidence_status == "blocked":
            if self.blocked_reason is None:
                raise ValueError("blocked evaluation evidence requires blocked_reason")
            object.__setattr__(
                self,
                "blocked_reason",
                _trimmed(self.blocked_reason, name="blocked_reason"),
            )
        elif self.blocked_reason is not None:
            raise ValueError("complete evaluation evidence cannot have blocked_reason")
        return self


class ReliablePlanMetricDelta(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    correctness_passed: int
    revisions: int
    nodes: int
    edges: int
    tokens: int
    actions: int
    duration_ms: int
    infrastructure_failures: int
    retries: int


def _metric_delta(
    candidate: ReliablePlanEvaluationResult,
    reference: ReliablePlanEvaluationResult,
) -> ReliablePlanMetricDelta:
    return ReliablePlanMetricDelta(
        correctness_passed=int(candidate.correctness.passed) - int(reference.correctness.passed),
        revisions=candidate.revision_count - reference.revision_count,
        nodes=candidate.graph_shape.node_count - reference.graph_shape.node_count,
        edges=candidate.graph_shape.edge_count - reference.graph_shape.edge_count,
        tokens=candidate.usage.total_tokens - reference.usage.total_tokens,
        actions=candidate.usage.total_actions - reference.usage.total_actions,
        duration_ms=candidate.usage.total_duration_ms - reference.usage.total_duration_ms,
        infrastructure_failures=(
            candidate.recovery.infrastructure_failure_count
            - reference.recovery.infrastructure_failure_count
        ),
        retries=candidate.recovery.retry_count - reference.recovery.retry_count,
    )


class ReliablePlanComparisonDeltas(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
    alternate_minus_luna: ReliablePlanMetricDelta
    luna_minus_legacy: ReliablePlanMetricDelta


class ReliablePlanComparisonArtifact(BaseModel):
    """Strict three-arm comparison with computed deltas."""

    model_config = {"extra": "forbid", "frozen": True}
    incident_id: Literal["fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"] = RELIABLE_PLAN_INCIDENT_ID
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"] = RELIABLE_PLAN_SCENARIO_ID
    qualification: ReliablePlanSkeletonQualification
    luna: ReliablePlanEvaluationResult
    alternate: ReliablePlanEvaluationResult
    legacy_baseline: ReliablePlanEvaluationResult
    deltas: ReliablePlanComparisonDeltas | None = None

    @model_validator(mode="after")
    def _validate_complete_comparison(self) -> Self:
        if not self.qualification.qualified:
            raise ValueError("comparison requires a qualified deterministic skeleton")
        if self.luna.baseline_kind != "dynamic_graph":
            raise ValueError("luna result must be a dynamic_graph arm")
        if self.alternate.baseline_kind != "dynamic_graph":
            raise ValueError("alternate result must be a dynamic_graph arm")
        if self.legacy_baseline.baseline_kind != "legacy_plan_then_execute":
            raise ValueError("legacy_baseline must use legacy_plan_then_execute")
        results = (self.luna, self.alternate, self.legacy_baseline)
        contract_identity = self.qualification.manifest.contract_identity
        if any(
            result.contract_identity != contract_identity for result in (self.luna, self.alternate)
        ):
            raise ValueError("evaluation results do not match qualification contract identity")
        if self.legacy_baseline.contract_identity.interaction_contract != "legacy":
            raise ValueError("legacy baseline must preserve its legacy contract identity")
        if len({result.run_id for result in results}) != 3:
            raise ValueError("comparison run IDs must be unique")
        if len({result.arm_id for result in results}) != 3:
            raise ValueError("comparison arm IDs must be unique")
        if self.luna.model_profiles == self.alternate.model_profiles:
            raise ValueError("alternate model profiles must differ from Luna")
        if any(result.evidence_status != "complete" for result in results):
            raise ValueError("complete comparison requires complete evidence for all three arms")
        computed = ReliablePlanComparisonDeltas(
            alternate_minus_luna=_metric_delta(self.alternate, self.luna),
            luna_minus_legacy=_metric_delta(self.luna, self.legacy_baseline),
        )
        if self.deltas is not None and self.deltas != computed:
            raise ValueError("comparison deltas do not match result metrics")
        object.__setattr__(self, "deltas", computed)
        return self


def evaluate_reliable_plan_projection(
    projection: GraphProjection,
    *,
    run_id: str,
    arm: ReliablePlanEvaluationArm,
    evidence_status: Literal["complete", "blocked"] = "complete",
    blocked_reason: str | None = None,
    baseline_kind: Literal["dynamic_graph", "legacy_plan_then_execute"] = "dynamic_graph",
    contract_identity: ReliablePlanContractIdentity | None = None,
) -> ReliablePlanEvaluationResult:
    """Build an evaluation artifact from public projection carrier facts."""
    latest_snapshot = latest_routine_snapshot_record(projection)
    snapshot = (
        output_record_payloads_view(projection).get(latest_snapshot.record_id)
        if latest_snapshot is not None
        else None
    )
    observed_identity = ReliablePlanContractIdentity.for_interaction(
        (snapshot.value.agent_interaction_contract or "legacy")
        if isinstance(snapshot, RoutineSnapshotRecord)
        else "legacy"
    )
    if contract_identity is not None and contract_identity != observed_identity:
        raise ValueError("evaluation identity differs from the frozen routine snapshot")
    states = node_states_view(projection)
    attempts = node_attempts_view(projection)
    runtime_retries = runtime_retry_counts_view(projection)
    payloads = [
        payload
        for node_id in states
        if (payload := node_payload_view(projection, node_id)) is not None
    ]
    batches = sorted(
        {
            value
            for payload in payloads
            if isinstance((value := payload.get("declared_batch_id")), str)
        }
    )
    horizons = sorted(
        {
            value
            for payload in payloads
            if isinstance((value := payload.get("planning_horizon")), int)
        }
    )
    usage = usage_metrics_view(projection)
    token_kinds = dict(usage["tokens_by_node_kind"])
    action_kinds = dict(usage["action_count_by_node_kind"])
    latency_kinds = dict(usage["latency_ms_by_node_kind"])
    leases = leases_view(projection)
    blockers = list(iter_final_invariant_blockers([], projection))
    failed_nodes = sum(state == "failed" for state in states.values())
    terminal = run_state(projection)
    return ReliablePlanEvaluationResult(
        run_id=run_id,
        arm_id=arm.arm_id,
        evidence_status=evidence_status,
        blocked_reason=blocked_reason,
        baseline_kind=baseline_kind,
        correctness=ReliablePlanCorrectnessMetrics(
            passed=(
                evidence_status == "complete"
                and terminal == "completed"
                and not blockers
                and failed_nodes == 0
            ),
            terminal_state=terminal,
            final_blocker_count=len(blockers),
            failed_node_count=failed_nodes,
        ),
        revision_count=sum(max(0, attempt - 1) for attempt in attempts.values()),
        graph_shape=ReliablePlanGraphShapeMetrics(
            node_count=len(states),
            edge_count=len(edges_view(projection)),
            batch_ids=tuple(batches),
            planning_horizons=tuple(horizons),
        ),
        usage=ReliablePlanUsageMetrics(
            total_tokens=sum(token_kinds.values()),
            total_actions=sum(action_kinds.values()),
            total_duration_ms=sum(latency_kinds.values()),
            tokens_by_node_kind=token_kinds,
            actions_by_node_kind=action_kinds,
            duration_ms_by_node_kind=latency_kinds,
        ),
        recovery=ReliablePlanRecoveryMetrics(
            infrastructure_failure_count=len(environment_failures_view(projection)),
            retry_count=sum(runtime_retries.values()),
            recovery_node_count=sum(
                len(entries) for entries in recovery_nodes_by_record_id_view(projection).values()
            ),
            revoked_lease_count=sum(lease.state == "revoked" for lease in leases.values()),
            active_lease_count=sum(lease.state == "active" for lease in leases.values()),
        ),
        model_profiles=arm,
        contract_identity=observed_identity,
    )
