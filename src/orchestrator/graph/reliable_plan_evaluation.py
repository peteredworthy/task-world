"""Typed qualification and comparison artifacts for reliable-plan dogfood."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha256
import json
from typing import Literal, Self, cast

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from orchestrator.config import ModelProfile
from orchestrator.graph.projection_models import GraphProjection
from orchestrator.graph.projection_queries import (
    edges_view,
    environment_failures_view,
    leases_view,
    node_attempts_view,
    node_payload_view,
    node_states_view,
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


def canonical_reliable_plan_scenario_manifest() -> "ReliablePlanScenarioManifest":
    """Return the server-owned incident manifest used to issue qualifications."""
    return ReliablePlanScenarioManifest(
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
        )
    )


def _trimmed(value: str, *, name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{name} must be nonempty after trimming")
    return trimmed


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


class ReliablePlanQualificationReceipt(BaseModel):
    """Canonical controller-accepted receipt over all ten stored observations."""

    model_config = {"extra": "forbid", "frozen": True}
    receipt_record_id: str = Field(min_length=1)
    runner_id: Literal["sqlite-controller-product-path-v1"] = RELIABLE_PLAN_RUNNER_ID
    runner_version: Literal[1] = RELIABLE_PLAN_RUNNER_VERSION
    incident_id: Literal["fff4f6b7-bf33-475f-8280-31ff5e1ef7ca"] = RELIABLE_PLAN_INCIDENT_ID
    skeleton_id: Literal["reliable-plan-fff4f6b7-v1"] = RELIABLE_PLAN_SCENARIO_ID
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observation_record_ids: tuple[str, ...] = Field(min_length=10, max_length=10)
    observation_hashes: tuple[str, ...] = Field(min_length=10, max_length=10)
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def reliable_plan_manifest_hash(manifest: ReliablePlanScenarioManifest) -> str:
    return _canonical_hash(manifest.model_dump(mode="json"))


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
) -> ReliablePlanEvaluationResult:
    """Build an evaluation artifact from public projection carrier facts."""
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
    )
