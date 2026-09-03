"""Explicit, process-external crash barriers for authorized recovery drills."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import secrets
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol, cast

import psutil
from pydantic import BaseModel, Field, ValidationError, model_validator

CRASH_BARRIER_ENV = "ORCHESTRATOR_GRAPH_CRASH_BARRIER"
CRASH_BARRIER_AUTHORIZATION = "operator-authorized-live-crash-drill"
CrashBarrierPoint = Literal[
    "after_staging_pre_witness",
    "after_witness_pre_finalization",
]


class CrashBarrierError(RuntimeError):
    """Raised when an enabled crash barrier cannot be proven safe."""


class CrashBarrierConfig(BaseModel):
    """Schema-1 exact operator-authorized run/execution barrier."""

    model_config = {"frozen": True, "extra": "forbid"}
    schema_version: Literal[1] = 1
    authorization: Literal["operator-authorized-live-crash-drill"]
    run_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    execution_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    point: CrashBarrierPoint

    @property
    def barrier_id(self) -> str:
        identity = f"{self.run_id}\0{self.execution_id}\0{self.point}"
        return hashlib.sha256(identity.encode()).hexdigest()


class CrashBarrierTarget(BaseModel):
    """The sole dynamic target class authorized for a two-crash drill."""

    model_config = {"frozen": True, "extra": "forbid"}
    kind: Literal["worker"]
    semantic_stage: Literal["effectful_batch"]


class CrashBarrierPlanConfig(BaseModel):
    """Schema-2 exact-run plan that dynamically binds two ordered attempts."""

    model_config = {"frozen": True, "extra": "forbid"}
    schema_version: Literal[2]
    authorization: Literal["operator-authorized-live-crash-drill"]
    run_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    nonce: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    target: CrashBarrierTarget
    slots: tuple[CrashBarrierPoint, CrashBarrierPoint]

    @model_validator(mode="after")
    def validate_ordered_slots(self) -> CrashBarrierPlanConfig:
        expected = ("after_staging_pre_witness", "after_witness_pre_finalization")
        if self.slots != expected:
            raise ValueError(f"slots must be exactly {expected!r}")
        return self

    @property
    def barrier_id(self) -> str:
        return hashlib.sha256(f"2\0{self.run_id}\0{self.nonce}".encode()).hexdigest()


CrashBarrierConfiguration = CrashBarrierConfig | CrashBarrierPlanConfig


class CrashBarrierState(BaseModel):
    """Schema-1 bounded externally readable/releasable state."""

    model_config = {"frozen": True, "extra": "forbid"}
    schema_version: Literal[1] = 1
    barrier_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    run_id: str
    execution_id: str
    point: CrashBarrierPoint
    status: Literal["reached", "released", "consumed_after_process_loss"]
    owner_pid: int = Field(gt=0)
    owner_create_time: float = Field(gt=0)
    release_token: str = Field(min_length=32, max_length=128)
    reached_at: datetime
    released_at: datetime | None = None


class CrashBarrierRecoveryProof(BaseModel):
    """Canonical prior-attempt facts required before slot 2 can bind."""

    model_config = {"frozen": True, "extra": "forbid"}
    node_id: str = Field(min_length=1, max_length=256)
    execution_id: str = Field(min_length=1, max_length=256)
    lease_generation: int = Field(ge=1)
    state: Literal["recovered"]
    completion_disposition: Literal["restored_unwitnessed"]
    retry_authorized: Literal[True]


class CrashBarrierObservation(BaseModel):
    """Typed canonical execution facts supplied at an exact runtime boundary."""

    model_config = {"frozen": True, "extra": "forbid"}
    run_id: str = Field(min_length=1, max_length=256)
    node_id: str = Field(min_length=1, max_length=256)
    execution_id: str = Field(min_length=1, max_length=256)
    lease_id: str = Field(min_length=1, max_length=256)
    lease_generation: int = Field(ge=1)
    node_kind: str = Field(min_length=1, max_length=64)
    node_role: str = Field(min_length=1, max_length=64)
    semantic_stage: str = Field(min_length=1, max_length=64)
    point: CrashBarrierPoint
    attempt_state: Literal["submission_staged", "completion_witnessed"]
    recovered_attempts: Annotated[tuple[CrashBarrierRecoveryProof, ...], Field(max_length=20)] = ()


class CrashBarrierSlotState(BaseModel):
    """One atomically bound execution in a schema-2 plan."""

    model_config = {"frozen": True, "extra": "forbid"}
    slot: Literal[1, 2]
    point: CrashBarrierPoint
    status: Literal["unbound", "reached", "released", "consumed_after_process_loss"] = "unbound"
    node_id: str | None = None
    execution_id: str | None = None
    lease_id: str | None = None
    lease_generation: int | None = Field(default=None, ge=1)
    owner_pid: int | None = Field(default=None, gt=0)
    owner_create_time: float | None = Field(default=None, gt=0)
    release_token: str | None = Field(default=None, min_length=32, max_length=128)
    reached_at: datetime | None = None
    released_at: datetime | None = None

    @model_validator(mode="after")
    def validate_binding(self) -> CrashBarrierSlotState:
        facts = (
            self.node_id,
            self.execution_id,
            self.lease_id,
            self.lease_generation,
            self.owner_pid,
            self.owner_create_time,
            self.release_token,
            self.reached_at,
        )
        if self.status == "unbound" and any(value is not None for value in facts):
            raise ValueError("an unbound slot cannot contain binding facts")
        if self.status != "unbound" and any(value is None for value in facts):
            raise ValueError("a bound slot requires complete binding facts")
        return self


class CrashBarrierPlanState(BaseModel):
    """Durable schema-2 state shared by replacement serving children."""

    model_config = {"frozen": True, "extra": "forbid"}
    schema_version: Literal[2]
    barrier_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    run_id: str
    nonce: str
    config_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    target: CrashBarrierTarget
    slots: tuple[CrashBarrierSlotState, CrashBarrierSlotState]

    @model_validator(mode="after")
    def validate_slots(self) -> CrashBarrierPlanState:
        if tuple(slot.slot for slot in self.slots) != (1, 2):
            raise ValueError("plan state must contain slots 1 and 2 in order")
        if tuple(slot.point for slot in self.slots) != (
            "after_staging_pre_witness",
            "after_witness_pre_finalization",
        ):
            raise ValueError("plan state slot boundaries are not canonical")
        return self


CrashBarrierReadback = CrashBarrierState | CrashBarrierPlanState


def schema_two_slot_lineage_authorized(
    first: CrashBarrierSlotState, observation: CrashBarrierObservation
) -> bool:
    """Decide slot-2 lineage solely from durable slot and canonical attempt facts."""
    if first.status != "consumed_after_process_loss":
        return False
    if (
        first.node_id != observation.node_id
        or first.execution_id == observation.execution_id
        or first.lease_generation is None
        or observation.lease_generation <= first.lease_generation
    ):
        return False
    return any(
        proof.node_id == first.node_id
        and proof.execution_id == first.execution_id
        and proof.lease_generation == first.lease_generation
        for proof in observation.recovered_attempts
    )


def bounded_crash_barrier_readback(state: CrashBarrierReadback | None) -> dict[str, object]:
    """Return bounded operator facts without exposing release capabilities."""
    if state is None:
        return {"status": "disabled"}
    if isinstance(state, CrashBarrierState):
        return {
            "schema_version": 1,
            "barrier_id": state.barrier_id,
            "run_id": state.run_id[:256],
            "execution_id": state.execution_id[:256],
            "point": state.point,
            "status": state.status,
            "owner_pid": state.owner_pid,
            "owner_create_time": state.owner_create_time,
            "reached_at": state.reached_at.isoformat(),
            "released_at": state.released_at.isoformat() if state.released_at else None,
        }
    return {
        "schema_version": 2,
        "barrier_id": state.barrier_id,
        "run_id": state.run_id[:256],
        "nonce": state.nonce[:128],
        "config_hash": state.config_hash,
        "target": state.target.model_dump(mode="json"),
        "slots": [
            {
                "slot": slot.slot,
                "point": slot.point,
                "status": slot.status,
                "node_id": slot.node_id[:256] if slot.node_id else None,
                "execution_id": slot.execution_id[:256] if slot.execution_id else None,
                "lease_id": slot.lease_id[:256] if slot.lease_id else None,
                "lease_generation": slot.lease_generation,
                "owner_pid": slot.owner_pid,
                "owner_create_time": slot.owner_create_time,
                "reached_at": slot.reached_at.isoformat() if slot.reached_at else None,
                "released_at": slot.released_at.isoformat() if slot.released_at else None,
            }
            for slot in state.slots
        ],
    }


class CrashBarrier(Protocol):
    async def wait_if_armed(
        self,
        *,
        run_id: str,
        execution_id: str,
        point: CrashBarrierPoint,
        observation: CrashBarrierObservation | None = None,
    ) -> None: ...

    def read_status(self) -> CrashBarrierReadback | None: ...


class DisabledCrashBarrier:
    """Default barrier: zero state and zero timing behavior."""

    async def wait_if_armed(
        self,
        *,
        run_id: str,
        execution_id: str,
        point: CrashBarrierPoint,
        observation: CrashBarrierObservation | None = None,
    ) -> None:
        del run_id, execution_id, point, observation

    def read_status(self) -> None:
        return None


class FileCrashBarrier:
    """Barrier coordinated through a filesystem lock and atomic state files."""

    def __init__(
        self,
        config: CrashBarrierConfiguration,
        *,
        state_dir: Path = Path(".orchestrator/state/crash-barriers"),
        poll_seconds: float = 0.05,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("crash barrier poll_seconds must be positive")
        self._config = config
        self._state_dir = state_dir
        self._poll_seconds = poll_seconds

    @property
    def state_path(self) -> Path:
        return self._state_dir / f"{self._config.barrier_id}.json"

    @property
    def lock_path(self) -> Path:
        return self._state_dir / f"{self._config.barrier_id}.lock"

    def release_path_for_slot(self, slot: int) -> Path:
        suffix = "" if isinstance(self._config, CrashBarrierConfig) else f".{slot}"
        return self._state_dir / f"{self._config.barrier_id}{suffix}.release"

    @property
    def release_path(self) -> Path:
        return self.release_path_for_slot(1)

    async def wait_if_armed(
        self,
        *,
        run_id: str,
        execution_id: str,
        point: CrashBarrierPoint,
        observation: CrashBarrierObservation | None = None,
    ) -> None:
        if isinstance(self._config, CrashBarrierConfig):
            if (run_id, execution_id, point) != (
                self._config.run_id,
                self._config.execution_id,
                self._config.point,
            ):
                return
            state = await asyncio.to_thread(self._reach_v1)
            if state is None:
                return
            while not await asyncio.to_thread(self._release_matches, state.release_token, 1):
                await asyncio.sleep(self._poll_seconds)
            await asyncio.to_thread(self._record_release_v1, state)
            return
        if run_id != self._config.run_id or observation is None:
            return
        if observation.run_id != run_id or observation.execution_id != execution_id:
            raise CrashBarrierError("crash barrier observation does not match dispatch scope")
        if observation.point != point:
            raise CrashBarrierError("crash barrier observation does not match boundary point")
        slot = await asyncio.to_thread(self._reach_v2, observation)
        if slot is None:
            return
        while not await asyncio.to_thread(
            self._release_matches, slot.release_token or "", slot.slot
        ):
            await asyncio.sleep(self._poll_seconds)
        await asyncio.to_thread(self._record_release_v2, slot)

    def read_status(self) -> CrashBarrierReadback | None:
        if isinstance(self._config, CrashBarrierConfig):
            return self._read_state_v1()
        return self._read_plan_or_initial()

    def reconcile_process_loss(self) -> None:
        """Consume prior-child slots only after their PIDs are definitively absent."""
        if isinstance(self._config, CrashBarrierConfig):
            return
        with self._locked():
            if self._read_raw_state() is None:
                return
            self._consume_dead_prior_process_slots(self._read_plan_or_initial())

    def release(self, *, slot: int = 1) -> CrashBarrierReadback:
        if isinstance(self._config, CrashBarrierConfig):
            state = self._read_state_v1()
            if state is None:
                raise CrashBarrierError("crash barrier has not been reached")
            if state.status == "reached":
                self._atomic_write(self.release_path, state.release_token)
            return state
        with self._locked():
            state = self._read_plan_or_initial()
            selected = self._plan_slot(state, slot)
            if selected.status != "reached" or selected.release_token is None:
                raise CrashBarrierError(f"crash barrier slot {slot} has not been reached")
            self._atomic_write(self.release_path_for_slot(slot), selected.release_token)
            return state

    def _reach_v1(self) -> CrashBarrierState | None:
        config = self._config
        if not isinstance(config, CrashBarrierConfig):
            raise CrashBarrierError("schema-1 operation used with schema-2 configuration")
        with self._locked():
            existing = self._read_state_v1()
            if existing is not None:
                self._validate_scope_v1(existing)
                if existing.status != "reached":
                    return None
                if self._same_current_owner(existing.owner_pid, existing.owner_create_time):
                    return existing
                self._require_owner_definitively_dead(existing.owner_pid)
                consumed = existing.model_copy(update={"status": "consumed_after_process_loss"})
                self._write_state(consumed)
                return None
            owner_pid, owner_create_time = self._current_owner()
            state = CrashBarrierState(
                barrier_id=config.barrier_id,
                run_id=config.run_id,
                execution_id=config.execution_id,
                point=config.point,
                status="reached",
                owner_pid=owner_pid,
                owner_create_time=owner_create_time,
                release_token=secrets.token_hex(24),
                reached_at=datetime.now(UTC),
            )
            self._write_state(state)
            return state

    def _reach_v2(self, observation: CrashBarrierObservation) -> CrashBarrierSlotState | None:
        config = self._plan_config()
        if (
            observation.node_kind != config.target.kind
            or observation.semantic_stage != config.target.semantic_stage
        ):
            return None
        expected_state = (
            "submission_staged"
            if observation.point == "after_staging_pre_witness"
            else "completion_witnessed"
        )
        if observation.attempt_state != expected_state:
            raise CrashBarrierError("crash barrier canonical attempt state is inconsistent")
        with self._locked():
            state = self._read_plan_or_initial()
            state = self._consume_dead_prior_process_slots(state)
            number = 1 if observation.point == config.slots[0] else 2
            slot = self._plan_slot(state, number)
            if slot.status == "reached":
                if slot.execution_id != observation.execution_id:
                    return None
                if self._same_current_owner(slot.owner_pid, slot.owner_create_time):
                    return slot
                assert slot.owner_pid is not None
                self._require_owner_definitively_dead(slot.owner_pid)
                consumed = slot.model_copy(update={"status": "consumed_after_process_loss"})
                self._write_state(self._replace_plan_slot(state, consumed))
                return None
            if slot.status != "unbound":
                return None
            if number == 2 and not self._slot_two_lineage_authorized(state, observation):
                return None
            owner_pid, owner_create_time = self._current_owner()
            bound = slot.model_copy(
                update={
                    "status": "reached",
                    "node_id": observation.node_id,
                    "execution_id": observation.execution_id,
                    "lease_id": observation.lease_id,
                    "lease_generation": observation.lease_generation,
                    "owner_pid": owner_pid,
                    "owner_create_time": owner_create_time,
                    "release_token": secrets.token_hex(24),
                    "reached_at": datetime.now(UTC),
                }
            )
            self._write_state(self._replace_plan_slot(state, bound))
            return bound

    def _consume_dead_prior_process_slots(
        self, state: CrashBarrierPlanState
    ) -> CrashBarrierPlanState:
        current = state
        for slot in state.slots:
            if slot.status != "reached" or slot.owner_pid is None:
                continue
            if self._same_current_owner(slot.owner_pid, slot.owner_create_time):
                continue
            self._require_owner_definitively_dead(slot.owner_pid)
            current = self._replace_plan_slot(
                current,
                slot.model_copy(update={"status": "consumed_after_process_loss"}),
            )
        if current != state:
            self._write_state(current)
        return current

    @staticmethod
    def _slot_two_lineage_authorized(
        state: CrashBarrierPlanState, observation: CrashBarrierObservation
    ) -> bool:
        return schema_two_slot_lineage_authorized(state.slots[0], observation)

    def _record_release_v1(self, state: CrashBarrierState) -> None:
        with self._locked():
            current = self._read_state_v1()
            if current is None:
                raise CrashBarrierError("crash barrier state disappeared before release")
            self._validate_scope_v1(current)
            if current.release_token != state.release_token:
                raise CrashBarrierError("crash barrier release token changed")
            self._write_state(
                current.model_copy(update={"status": "released", "released_at": datetime.now(UTC)})
            )

    def _record_release_v2(self, slot: CrashBarrierSlotState) -> None:
        with self._locked():
            current = self._read_plan_or_initial()
            selected = self._plan_slot(current, slot.slot)
            if selected.status != "reached" or selected.release_token != slot.release_token:
                raise CrashBarrierError("crash barrier slot changed before release")
            released = selected.model_copy(
                update={"status": "released", "released_at": datetime.now(UTC)}
            )
            self._write_state(self._replace_plan_slot(current, released))

    def _release_matches(self, token: str, slot: int) -> bool:
        try:
            supplied = self.release_path_for_slot(slot).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return False
        except (OSError, UnicodeError) as exc:
            raise CrashBarrierError(f"crash barrier release cannot be read: {exc}") from exc
        return secrets.compare_digest(supplied, token)

    def _read_state_v1(self) -> CrashBarrierState | None:
        raw = self._read_raw_state()
        if raw is None:
            return None
        try:
            return CrashBarrierState.model_validate_json(raw)
        except ValidationError as exc:
            raise CrashBarrierError("crash barrier state is malformed") from exc

    def _read_plan_or_initial(self) -> CrashBarrierPlanState:
        raw = self._read_raw_state()
        if raw is not None:
            try:
                state = CrashBarrierPlanState.model_validate_json(raw)
            except ValidationError as exc:
                raise CrashBarrierError("crash barrier plan state is malformed") from exc
            self._validate_scope_v2(state)
            return state
        return self._initial_plan_state()

    def _initial_plan_state(self) -> CrashBarrierPlanState:
        config = self._plan_config()
        return CrashBarrierPlanState(
            schema_version=2,
            barrier_id=config.barrier_id,
            run_id=config.run_id,
            nonce=config.nonce,
            config_hash=self._config_hash(config),
            target=config.target,
            slots=(
                CrashBarrierSlotState(slot=1, point=config.slots[0]),
                CrashBarrierSlotState(slot=2, point=config.slots[1]),
            ),
        )

    def _read_raw_state(self) -> str | None:
        try:
            return self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise CrashBarrierError(f"crash barrier state cannot be read: {exc}") from exc

    def _validate_scope_v1(self, state: CrashBarrierState) -> None:
        config = self._config
        assert isinstance(config, CrashBarrierConfig)
        if (
            state.barrier_id != config.barrier_id
            or state.run_id != config.run_id
            or state.execution_id != config.execution_id
            or state.point != config.point
        ):
            raise CrashBarrierError("crash barrier state does not match configured scope")

    def _validate_scope_v2(self, state: CrashBarrierPlanState) -> None:
        config = self._plan_config()
        if (
            state.barrier_id != config.barrier_id
            or state.run_id != config.run_id
            or state.nonce != config.nonce
            or state.target != config.target
            or state.config_hash != self._config_hash(config)
        ):
            raise CrashBarrierError("crash barrier plan state does not match configured scope")

    @staticmethod
    def _config_hash(config: CrashBarrierPlanConfig) -> str:
        raw = config.model_dump_json(exclude={"authorization"}).encode()
        return hashlib.sha256(raw).hexdigest()

    def _plan_config(self) -> CrashBarrierPlanConfig:
        if not isinstance(self._config, CrashBarrierPlanConfig):
            raise CrashBarrierError("schema-2 operation used with schema-1 configuration")
        return self._config

    @staticmethod
    def _plan_slot(state: CrashBarrierPlanState, slot: int) -> CrashBarrierSlotState:
        if slot not in (1, 2):
            raise CrashBarrierError("crash barrier slot must be 1 or 2")
        return state.slots[slot - 1]

    @staticmethod
    def _replace_plan_slot(
        state: CrashBarrierPlanState, slot: CrashBarrierSlotState
    ) -> CrashBarrierPlanState:
        slots = list(state.slots)
        slots[slot.slot - 1] = slot
        return state.model_copy(update={"slots": tuple(slots)})

    @staticmethod
    def _current_owner() -> tuple[int, float]:
        pid = os.getpid()
        try:
            return pid, psutil.Process(pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
            raise CrashBarrierError(f"cannot capture crash barrier owner identity: {exc}") from exc

    @staticmethod
    def _same_current_owner(pid: int | None, create_time: float | None) -> bool:
        if pid is None or create_time is None or pid != os.getpid():
            return False
        try:
            observed = psutil.Process(pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
            raise CrashBarrierError(f"cannot inspect reached barrier owner: {exc}") from exc
        return abs(observed - create_time) <= 0.001

    @staticmethod
    def _require_owner_definitively_dead(pid: int) -> None:
        try:
            psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            return
        except (psutil.AccessDenied, OSError) as exc:
            raise CrashBarrierError(f"cannot inspect prior crash barrier owner: {exc}") from exc
        raise CrashBarrierError(
            "prior crash barrier owner PID is live or reused; refusing to consume its slot"
        )

    def _write_state(self, state: CrashBarrierReadback) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.state_path, state.model_dump_json())

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise CrashBarrierError(f"crash barrier lock is unavailable: {exc}") from exc

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def crash_barrier_from_environment(
    environ: Mapping[str, str],
    *,
    state_dir: Path = Path(".orchestrator/state/crash-barriers"),
    reconcile_process_loss: bool = False,
) -> CrashBarrier:
    """Load a barrier, failing closed on every non-empty invalid config."""
    raw = environ.get(CRASH_BARRIER_ENV)
    if raw is None or not raw.strip():
        return DisabledCrashBarrier()
    if len(raw) > 4_096:
        raise CrashBarrierError(f"{CRASH_BARRIER_ENV} exceeds 4096 bytes")
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CrashBarrierError(f"{CRASH_BARRIER_ENV} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise CrashBarrierError(f"{CRASH_BARRIER_ENV} must be a JSON object")
    data = cast(dict[str, object], decoded)
    try:
        schema_version = data.get("schema_version", 1)
        config: CrashBarrierConfiguration
        if schema_version == 1:
            config = CrashBarrierConfig.model_validate(data)
        elif schema_version == 2:
            config = CrashBarrierPlanConfig.model_validate(data)
        else:
            raise CrashBarrierError(f"{CRASH_BARRIER_ENV} schema_version must be exactly 1 or 2")
    except ValidationError as exc:
        raise CrashBarrierError(f"{CRASH_BARRIER_ENV} is invalid: {exc}") from exc
    barrier = FileCrashBarrier(config, state_dir=state_dir)
    if reconcile_process_loss:
        barrier.reconcile_process_loss()
    return barrier


__all__ = [
    "CRASH_BARRIER_AUTHORIZATION",
    "CRASH_BARRIER_ENV",
    "CrashBarrier",
    "CrashBarrierConfig",
    "CrashBarrierError",
    "CrashBarrierObservation",
    "CrashBarrierPlanConfig",
    "CrashBarrierPlanState",
    "CrashBarrierPoint",
    "CrashBarrierReadback",
    "CrashBarrierRecoveryProof",
    "CrashBarrierSlotState",
    "CrashBarrierState",
    "CrashBarrierTarget",
    "DisabledCrashBarrier",
    "FileCrashBarrier",
    "bounded_crash_barrier_readback",
    "crash_barrier_from_environment",
]
