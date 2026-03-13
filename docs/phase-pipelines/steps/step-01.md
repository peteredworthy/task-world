# Step 1: Config Models + Enums (M1)

Define `PhaseType`, `PhaseConfig`, and the `phases` field on `TaskConfig`. This is purely additive type/model work with no runtime effect — it unblocks every subsequent step.

## Intent Verification
**Original Intent**: Add all new config types (`PhaseType` enum, `PhaseConfig` model, `phases` field on `TaskConfig`) so the rest of the system can reference them without touching the engine, executor, or DB.
**Functionality to Produce**:
- `PhaseType(str, Enum)` with 8 values: `build`, `verify`, `plan`, `summarize`, `gap_check`, `script`, `auto_verify`, `human_review`
- `PhaseConfig(BaseModel)` with fields: `type`, `prompt`, `profile`, `condition`, `cmd`, `retry_target`
- `TaskConfig.phases: list[PhaseConfig] | None = None`
- `@model_validator` on `TaskConfig` rejecting `phases` + `fan_out` co-existence and validating `retry_target` bounds
- Unit tests in `tests/unit/test_phase_config.py`

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_phase_config.py -v` — all new tests pass
- `uv run pytest tests/unit/ -v` — no existing tests broken
- `uv run pyright src/orchestrator/config/` — no type errors

---

## Task 1: Add PhaseType Enum

**Description**: Add `PhaseType(str, Enum)` to `src/orchestrator/config/enums.py` with all 8 phase type values.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/config/enums.py`
- [ ] Add `PhaseType(str, Enum)` with values: `build = "build"`, `verify = "verify"`, `plan = "plan"`, `summarize = "summarize"`, `gap_check = "gap_check"`, `script = "script"`, `auto_verify = "auto_verify"`, `human_review = "human_review"`
- [ ] Verify: `from orchestrator.config.enums import PhaseType; print(list(PhaseType))` succeeds

**Dependencies**
- None — this is the first task

**References**
- `docs/phase-pipelines/plan.md` — M1 step 1
- `docs/phase-pipelines/architecture.md` — PhaseType values

**Constraints**
- Use `str, Enum` mixin so values serialize to strings in JSON

**Functionality (Expected Outcomes)**
- [ ] `PhaseType` importable from `src/orchestrator/config/enums.py`
- [ ] All 8 values present

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.enums import PhaseType; assert len(list(PhaseType)) == 8; print('OK')"` succeeds

---

## Task 2: Add PhaseConfig Model

**Description**: Add `PhaseConfig(BaseModel)` to `src/orchestrator/config/models.py` with all required fields.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/config/models.py`
- [ ] Import `PhaseType` from enums
- [ ] Add `PhaseConfig(BaseModel)` with fields:
  - `type: PhaseType`
  - `prompt: str | None = None`
  - `profile: ModelProfile | None = None`
  - `condition: str | None = None`
  - `cmd: str | None = None`
  - `retry_target: int | None = None`
- [ ] Verify JSON round-trip works for all fields

**Dependencies**
- [ ] Task 1 must be complete (`PhaseType` defined)

**References**
- `docs/phase-pipelines/architecture.md` — PhaseConfig field definitions
- `docs/phase-pipelines/clarifications.md` — Q5: int keys in JSON serialization

**Constraints**
- `profile` MUST use `ModelProfile` from `orchestrator.config.enums` — it IS already defined there (class `ModelProfile(str, Enum)`). Do NOT use `str | None`. Import it alongside the other enums at the top of `models.py`. The existing imports line already imports other enums from `orchestrator.config.enums`; add `ModelProfile` to that import.

**Functionality (Expected Outcomes)**
- [ ] `PhaseConfig` importable from `src/orchestrator/config/models.py`
- [ ] All 6 fields present with correct defaults

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.models import PhaseConfig; from orchestrator.config.enums import PhaseType; pc = PhaseConfig(type=PhaseType.build); print(pc.model_dump())"` succeeds

---

## Task 3: Extend TaskConfig with phases Field and Validators

**Description**: Add `phases: list[PhaseConfig] | None = None` to `TaskConfig` and add a `@model_validator` enforcing mutual exclusion with `fan_out` and `retry_target` bounds.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/config/models.py`
- [ ] Add `phases: list[PhaseConfig] | None = None` to `TaskConfig`
- [ ] ⚠️ HARDENING NOTE (Gap 6): `TaskConfig` already has a `@model_validator(mode="after")` at line ~193. Pydantic allows only ONE `@model_validator(mode="after")` per class — adding a second one **silently overrides the first**, breaking all existing mutual exclusion checks (`fan_out + task_context`, `fan_out + script`, `script + task_context`). You MUST extend the EXISTING validator body, not add a new method.
- [ ] EXTEND the existing `@model_validator(mode="after")` at line ~193 in `TaskConfig` — add the phases validation checks INSIDE the existing validator body:
  - If `self.phases` is not None and `self.fan_out` is not None → raise `ValueError("phases and fan_out are mutually exclusive")`
  - If `self.phases` is not None and `self.script` is not None → raise `ValueError("phases and script are mutually exclusive")` — both define execution behavior; co-existence is ambiguous
  - For each phase in `self.phases` where `phase.retry_target is not None`: validate that `retry_target < phase_index` (i.e., it must point to an earlier phase in the list — use `enumerate(self.phases)` to get the index)

**Dependencies**
- [ ] Task 2 must be complete (`PhaseConfig` defined)

**References**
- `docs/phase-pipelines/clarifications.md` — Q3: phases mutually exclusive with fan_out; Q4: retry_target validation at TaskConfig level

**Constraints**
- Validator must not break existing `TaskConfig` instances that have no `phases` field (guard with `if self.phases is not None`)
- `retry_target` validation requires iterating with `enumerate(self.phases)`: for phase at index `i`, `retry_target` must be < `i` (phase 0 cannot have a retry_target; phase 1 can only retry to index 0; etc.)
- The phases validation logic MUST be added inside the existing `@model_validator(mode="after")` body, NOT as a separate validator method — Pydantic only allows one `mode="after"` validator per class

**Functionality (Expected Outcomes)**
- [ ] `TaskConfig` accepts `phases` alongside `task_context`, `verifier`, `auto_verify`
- [ ] `TaskConfig(phases=[...], fan_out=...)` raises `ValidationError`
- [ ] `retry_target` pointing to index >= current phase index raises `ValidationError`

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.config.models import TaskConfig, PhaseConfig; from orchestrator.config.enums import PhaseType; tc = TaskConfig(task_context='test', phases=[PhaseConfig(type=PhaseType.build)]); print('OK')"` succeeds
- [ ] Passing both `phases` and `fan_out` raises `ValidationError`

---

## Task 4: Write Unit Tests

**Description**: Create `tests/unit/test_phase_config.py` covering all validation rules for `PhaseType`, `PhaseConfig`, and the extended `TaskConfig`.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_phase_config.py`
- [ ] Write tests:
  - `test_phase_type_values`: all 8 `PhaseType` values exist
  - `test_phase_config_all_types`: `PhaseConfig` accepts all 8 `PhaseType` values
  - `test_phase_config_json_roundtrip`: all fields survive `model_dump_json` / `model_validate_json`
  - `test_task_config_phases_coexist_with_verifier`: `phases` + `verifier` accepted
  - `test_task_config_phases_fan_out_rejected`: `phases` + `fan_out` raises `ValidationError`
  - `test_retry_target_invalid_index`: `retry_target >= phase_index` raises `ValidationError`
  - `test_retry_target_valid_index`: `retry_target < phase_index` accepted
- [ ] Run: `uv run pytest tests/unit/test_phase_config.py -v`

**Dependencies**
- [ ] Tasks 1–3 must be complete

**References**
- `docs/phase-pipelines/step-01-plan.md` — Tasks section, verification cases

**Constraints**
- Tests must not import from `tests/` fixtures that may not exist yet; use inline construction

**Functionality (Expected Outcomes)**
- [ ] All 7 test cases pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_phase_config.py -v` — all pass
- [ ] `uv run pytest tests/unit/ -v` — no regressions

---
