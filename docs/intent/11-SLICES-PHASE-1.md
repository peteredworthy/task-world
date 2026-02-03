# Implementation Slices: Phase 1 - Foundation

**Goal:** Establish project structure, configuration models, routine loading, and basic state management.

**End state:** Can load a routine from YAML and create an in-memory run with initial state.

---

## Slice 1.1: Project Skeleton

### Goal
Create a working Python project with dependencies, tooling, and the ability to import the main module.

### Prerequisites
- None (this is the first slice)

### Deliverables

```
orchestrator/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── src/
│   └── orchestrator/
│       ├── __init__.py
│       └── __version__.py
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── unit/
        └── test_import.py
```

### Architecture Constraints

1. **Use `uv` for package management** - Fast, reliable, and consistent
2. **Use `src/` layout** - Prevents accidental imports from project root
3. **Export version from package** - Enables `orchestrator.__version__`

### Implementation Steps

1. Create `pyproject.toml` with:
   ```toml
   [project]
   name = "orchestrator"
   version = "0.1.0"
   requires-python = ">=3.11"
   dependencies = [
       "pydantic>=2.0",
       "pydantic-settings>=2.0",
       "pyyaml>=6.0",
       "sqlalchemy>=2.0",
       "aiosqlite>=0.19",
       "fastapi>=0.100",
       "uvicorn[standard]>=0.23",
       "httpx>=0.25",
       "websockets>=12.0",
       "gitpython>=3.1",
       "click>=8.1",
       "aiofiles>=23.0",
   ]
   
   [project.optional-dependencies]
   dev = [
       "pytest>=7.4",
       "pytest-asyncio>=0.21",
       "pytest-cov>=4.1",
       "pyright>=1.1",
       "ruff>=0.1",
   ]
   
   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"
   
   [tool.hatch.build.targets.wheel]
   packages = ["src/orchestrator"]
   
   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   testpaths = ["tests"]
   
   [tool.ruff]
   line-length = 100
   
   [tool.pyright]
   pythonVersion = "3.11"
   typeCheckingMode = "strict"
   ```

2. Create `src/orchestrator/__init__.py`:
   ```python
   """Orchestrator - LLM Agent Workflow Management."""
   from orchestrator.__version__ import __version__
   
   __all__ = ["__version__"]
   ```

3. Create `src/orchestrator/__version__.py`:
   ```python
   __version__ = "0.1.0"
   ```

4. Create `tests/conftest.py`:
   ```python
   """Shared test fixtures."""
   import pytest
   from pathlib import Path
   import tempfile
   from datetime import datetime
   
   @pytest.fixture
   def tmp_path_factory_custom(tmp_path):
       """Temporary directory for test files."""
       return tmp_path
   
   @pytest.fixture
   def fixed_time():
       """Fixed datetime for deterministic tests."""
       return datetime(2025, 1, 15, 10, 30, 0)
   ```

5. Create `tests/unit/test_import.py`:
   ```python
   """Test that the package can be imported."""
   
   def test_import_orchestrator():
       import orchestrator
       assert orchestrator.__version__ == "0.1.0"
   ```

### Verification

#### Unit Tests
```bash
uv sync
uv run pytest tests/unit/test_import.py -v
```

**Expected:** Test passes, module imports successfully.

#### Integration Tests
None for this slice.

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] `uv sync` succeeds
- [ ] `uv run python -c "import orchestrator"` succeeds
- [ ] `uv run pytest` passes
- [ ] `uv run pyright src/` has no errors
- [ ] `uv run ruff check src/` has no errors

---

## Slice 1.2: Configuration Models

### Goal
Define Pydantic models for all configuration: global config, project config, routine config. These are data structures only - no loading logic yet.

### Prerequisites
- Slice 1.1 complete

### Deliverables

```
src/orchestrator/
├── config/
│   ├── __init__.py
│   ├── models.py      # All config Pydantic models
│   └── enums.py       # Status enums
tests/unit/
└── test_config_models.py
```

### Architecture Constraints

1. **No `ref:` or `use:` fields** - Reject inheritance. The implementing LLM may think "it would be convenient to add inheritance" - NO. This was explicitly decided against. If the YAML contains `ref:` or `use:`, validation must fail.

2. **All fields have defaults or are required** - No Optional without default. This forces explicit handling.

3. **Enums for all categorical values** - Status, priority, etc. must be enums, not strings.

4. **model_overrides structure** - Task can have model-specific prompt overrides:
   ```python
   model_overrides: dict[str, dict[str, str]] | None = None
   ```

### Implementation Steps

1. Create `src/orchestrator/config/enums.py`:
   ```python
   from enum import Enum
   
   class RunStatus(str, Enum):
       DRAFT = "draft"
       QUEUED = "queued"
       ACTIVE = "active"
       PAUSED = "paused"
       COMPLETED = "completed"
       FAILED = "failed"
   
   class TaskStatus(str, Enum):
       PENDING = "pending"
       BUILDING = "building"
       VERIFYING = "verifying"
       COMPLETED = "completed"
       FAILED = "failed"
   
   class ChecklistStatus(str, Enum):
       OPEN = "open"
       DONE = "done"
       NOT_APPLICABLE = "not_applicable"
       BLOCKED = "blocked"
   
   class Priority(str, Enum):
       CRITICAL = "critical"
       EXPECTED = "expected"
       NICE = "nice"
   
   class AgentType(str, Enum):
       OPENHANDS_LOCAL = "openhands_local"
       OPENHANDS_DOCKER = "openhands_docker"
       CLI_SUBPROCESS = "cli_subprocess"
       USER_MANAGED = "user_managed"
   
   class RoutineSource(str, Enum):
       LOCAL = "local"
       PROJECT = "project"
       EXTERNAL = "external"
   ```

2. Create `src/orchestrator/config/models.py` with all models. Key models:

   ```python
   from pydantic import BaseModel, Field, field_validator
   from typing import Any, Literal
   from .enums import Priority
   
   class RequirementConfig(BaseModel):
       """A single requirement in a task."""
       id: str
       desc: str
       must: bool = True
       priority: Priority = Priority.CRITICAL
   
   class AutoVerifyItemConfig(BaseModel):
       """A single auto-verify command."""
       id: str
       cmd: str
       must: bool = True
   
   class AutoVerifyConfig(BaseModel):
       """Auto-verification configuration."""
       items: list[AutoVerifyItemConfig] = Field(default_factory=list)
       tail_lines: int = 20
   
   class RubricItemConfig(BaseModel):
       """A single rubric question for verifier."""
       id: str
       text: str
   
   class SubmissionTemplateConfig(BaseModel):
       """Verifier submission template."""
       grade_scale: list[str] = Field(default=["A", "B", "C", "D", "F"])
       require_reason_if_below: str = "A"
       require_remediation_if_below: str = "B"
   
   class VerifierConfig(BaseModel):
       """Verifier configuration."""
       rubric: list[RubricItemConfig] = Field(default_factory=list)
       submission_template: SubmissionTemplateConfig = Field(
           default_factory=SubmissionTemplateConfig
       )
   
   class RetryConfig(BaseModel):
       """Retry configuration."""
       max_attempts: int = 3
   
   class TaskConfig(BaseModel):
       """A task within a step."""
       id: str
       title: str
       task_context: str
       model_overrides: dict[str, dict[str, str]] | None = None
       requirements: list[RequirementConfig] = Field(default_factory=list)
       auto_verify: AutoVerifyConfig = Field(default_factory=AutoVerifyConfig)
       verifier: VerifierConfig = Field(default_factory=VerifierConfig)
       retry: RetryConfig = Field(default_factory=RetryConfig)
   
   class StepConfig(BaseModel):
       """A step within a routine.

       Always uses `tasks` (list). No singular `task` shorthand -- keeps the model
       simple and avoids an ambiguous dual-field validator.
       """
       id: str
       title: str
       step_context: str | None = None
       tasks: list[TaskConfig] = Field(min_length=1)
   
   class RoutineInputConfig(BaseModel):
       """An input parameter for a routine."""
       name: str
       required: bool = True
       default: Any = None
       description: str | None = None
   
   class RoutineConfig(BaseModel):
       """A complete routine definition."""
       id: str
       name: str
       description: str | None = None
       inputs: list[RoutineInputConfig] = Field(default_factory=list)
       steps: list[StepConfig]
       
       # These fields are forbidden - reject YAML with inheritance
       @field_validator("*", mode="before")
       @classmethod
       def reject_inheritance(cls, v, info):
           if isinstance(v, dict):
               if "ref" in v or "use" in v:
                   raise ValueError(
                       f"Field '{info.field_name}' contains 'ref' or 'use'. "
                       "Inheritance is not supported. Use explicit definitions."
                   )
           return v
   ```

3. Create `tests/unit/test_config_models.py`:
   ```python
   import pytest
   from orchestrator.config.models import (
       RoutineConfig, StepConfig, TaskConfig, RequirementConfig
   )
   from orchestrator.config.enums import Priority
   
   def test_requirement_defaults():
       req = RequirementConfig(id="R1", desc="Test requirement")
       assert req.must is True
       assert req.priority == Priority.CRITICAL
   
   def test_task_with_requirements():
       task = TaskConfig(
           id="T1",
           title="Test Task",
           task_context="Do something",
           requirements=[
               RequirementConfig(id="R1", desc="Req 1"),
               RequirementConfig(id="R2", desc="Req 2", priority=Priority.NICE),
           ]
       )
       assert len(task.requirements) == 2
       assert task.requirements[1].priority == Priority.NICE
   
   def test_routine_complete():
       routine = RoutineConfig(
           id="test-routine",
           name="Test Routine",
           steps=[
               StepConfig(
                   id="S-01",
                   title="Step 1",
                   tasks=[TaskConfig(
                       id="T-01",
                       title="Task 1",
                       task_context="Context",
                   )]
               )
           ]
       )
       assert routine.id == "test-routine"
       assert len(routine.steps) == 1
   
   def test_model_overrides():
       task = TaskConfig(
           id="T1",
           title="Task",
           task_context="Default context",
           model_overrides={
               "claude-sonnet": {"task_context": "Claude-specific context"},
           }
       )
       assert task.model_overrides["claude-sonnet"]["task_context"] == "Claude-specific context"
   
   def test_reject_ref_inheritance():
       """CRITICAL: ref/use inheritance must be rejected."""
       with pytest.raises(ValueError, match="ref.*not supported"):
           RoutineConfig(
               id="test",
               name="Test",
               steps=[{"ref": "some-step"}]  # This must fail
           )
   
   def test_reject_use_inheritance():
       """CRITICAL: ref/use inheritance must be rejected."""
       with pytest.raises(ValueError, match="use.*not supported"):
           StepConfig(
               id="S1",
               title="Step",
               tasks=[{"use": "some-task"}]  # This must fail
           )
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_config_models.py -v
```

**Expected:** All tests pass, especially the inheritance rejection tests.

#### Integration Tests
None for this slice.

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] All config models defined in `models.py`
- [ ] All enums defined in `enums.py`
- [ ] Unit tests pass
- [ ] Pyright has no errors
- [ ] `ref`/`use` rejection test passes (CRITICAL)

---

## Slice 1.3: Routine Loading

### Goal
Load routine definitions from YAML files. Parse, validate, and return RoutineConfig objects.

### Prerequisites
- Slice 1.2 complete

### Deliverables

```
src/orchestrator/
├── routines/
│   ├── __init__.py
│   ├── loader.py      # YAML loading
│   └── errors.py      # Custom exceptions
tests/
├── unit/
│   └── test_routine_loader.py
├── integration/
│   └── test_routine_loading.py
└── fixtures/
    └── routines/
        ├── valid_simple.yaml
        ├── valid_complete.yaml
        └── invalid_with_ref.yaml
```

### Architecture Constraints

1. **Loader is a pure function** - Takes path, returns RoutineConfig. No side effects.
   ```python
   def load_routine(path: Path) -> RoutineConfig:
       # Pure: read file, parse, validate, return
   ```

2. **Explicit error types** - RoutineNotFoundError, RoutineParseError, RoutineValidationError

3. **No automatic discovery** - The loader loads ONE file. Discovery is a separate concern.

### Implementation Steps

1. Create `src/orchestrator/routines/errors.py`:
   ```python
   class RoutineError(Exception):
       """Base class for routine errors."""
       pass
   
   class RoutineNotFoundError(RoutineError):
       def __init__(self, path: str):
           self.path = path
           super().__init__(f"Routine not found: {path}")
   
   class RoutineParseError(RoutineError):
       def __init__(self, path: str, detail: str):
           self.path = path
           self.detail = detail
           super().__init__(f"Failed to parse routine {path}: {detail}")
   
   class RoutineValidationError(RoutineError):
       def __init__(self, path: str, errors: list[str]):
           self.path = path
           self.errors = errors
           super().__init__(f"Routine validation failed {path}: {errors}")
   ```

2. Create `src/orchestrator/routines/loader.py`:
   ```python
   from pathlib import Path
   import yaml
   from pydantic import ValidationError
   
   from orchestrator.config.models import RoutineConfig
   from .errors import RoutineNotFoundError, RoutineParseError, RoutineValidationError
   
   def load_routine_from_path(path: Path) -> RoutineConfig:
       """
       Load a routine from a YAML file.
       
       Args:
           path: Path to the YAML file
           
       Returns:
           Validated RoutineConfig
           
       Raises:
           RoutineNotFoundError: If file doesn't exist
           RoutineParseError: If YAML is invalid
           RoutineValidationError: If content doesn't match schema
       """
       if not path.exists():
           raise RoutineNotFoundError(str(path))
       
       try:
           content = path.read_text()
           data = yaml.safe_load(content)
       except yaml.YAMLError as e:
           raise RoutineParseError(str(path), str(e))
       
       if data is None:
           raise RoutineParseError(str(path), "Empty file")
       
       # Handle both wrapped and unwrapped format
       if "routine" in data:
           data = data["routine"]
       
       try:
           return RoutineConfig.model_validate(data)
       except ValidationError as e:
           errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
           raise RoutineValidationError(str(path), errors)
   ```

3. Create test fixtures in `tests/fixtures/routines/`:

   `valid_simple.yaml`:
   ```yaml
   routine:
     id: simple-routine
     name: Simple Routine
     steps:
       - id: S-01
         title: Only Step
         tasks:
           - id: T-01
             title: Only Task
             task_context: Do something simple
             requirements:
               - id: R1
                 desc: Complete the task
   ```

   `valid_complete.yaml`:
   ```yaml
   routine:
     id: complete-routine
     name: Complete Routine
     description: A fully specified routine
     inputs:
       - name: feature_name
         required: true
       - name: branch
         required: false
         default: main
     steps:
       - id: S-01
         title: Planning
         step_context: Plan the feature
         tasks:
           - id: T-01
             title: Create Plan
             task_context: Create a plan for {{feature_name}}
             model_overrides:
               claude-sonnet:
                 task_context: Use structured thinking for {{feature_name}}
             requirements:
               - id: R1
                 desc: Create plan.md
                 must: true
                 priority: critical
               - id: R2
                 desc: Include timeline
                 priority: expected
             auto_verify:
               items:
                 - id: check_file
                   cmd: test -f plan.md
               tail_lines: 20
             verifier:
               rubric:
                 - id: quality
                   text: Is the plan clear?
               submission_template:
                 grade_scale: [A, B, C, D, F]
                 require_reason_if_below: A
                 require_remediation_if_below: B
             retry:
               max_attempts: 3
       - id: S-02
         title: Implementation
         step_context: Implement the feature
         tasks:
           - id: T-02
             title: Write Code
             task_context: Implement {{feature_name}}
             requirements:
               - id: R3
                 desc: Write implementation code
                 priority: critical
               - id: R4
                 desc: Follow coding standards
                 priority: expected
               - id: R5
                 desc: Add inline comments
                 priority: nice
             retry:
               max_attempts: 2
           - id: T-03
             title: Write Tests
             task_context: Write tests for {{feature_name}}
             requirements:
               - id: R6
                 desc: Unit tests pass
                 priority: critical
             auto_verify:
               items:
                 - id: run_tests
                   cmd: pytest tests/
               tail_lines: 30
   ```

   `invalid_with_ref.yaml`:
   ```yaml
   routine:
     id: invalid-routine
     name: Invalid Routine
     steps:
       - ref: shared/common-step  # This should fail validation
   ```

4. Create `tests/unit/test_routine_loader.py`:
   ```python
   import pytest
   from pathlib import Path
   from orchestrator.routines.loader import load_routine_from_path
   from orchestrator.routines.errors import (
       RoutineNotFoundError, RoutineParseError, RoutineValidationError
   )
   
   def test_load_nonexistent_file(tmp_path):
       with pytest.raises(RoutineNotFoundError):
           load_routine_from_path(tmp_path / "nonexistent.yaml")
   
   def test_load_invalid_yaml(tmp_path):
       bad_file = tmp_path / "bad.yaml"
       bad_file.write_text("not: valid: yaml: [")
       with pytest.raises(RoutineParseError):
           load_routine_from_path(bad_file)
   
   def test_load_empty_file(tmp_path):
       empty_file = tmp_path / "empty.yaml"
       empty_file.write_text("")
       with pytest.raises(RoutineParseError, match="Empty"):
           load_routine_from_path(empty_file)
   
   def test_load_missing_required_field(tmp_path):
       bad_file = tmp_path / "missing.yaml"
       bad_file.write_text("routine:\n  name: No ID")  # Missing 'id'
       with pytest.raises(RoutineValidationError):
           load_routine_from_path(bad_file)
   ```

5. Create `tests/integration/test_routine_loading.py`:
   ```python
   import pytest
   from pathlib import Path
   from orchestrator.routines.loader import load_routine_from_path
   from orchestrator.routines.errors import RoutineValidationError
   from orchestrator.config.enums import Priority
   
   FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"
   
   def test_load_simple_routine():
       routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
       assert routine.id == "simple-routine"
       assert len(routine.steps) == 1
       assert routine.steps[0].tasks[0].id == "T-01"

   def test_load_complete_routine():
       routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
       assert routine.id == "complete-routine"
       assert len(routine.inputs) == 2
       assert routine.inputs[0].required is True
       assert routine.inputs[1].default == "main"

       # Step 1: Planning (single task)
       assert len(routine.steps) == 2
       task = routine.steps[0].tasks[0]
       assert task.model_overrides is not None
       assert "claude-sonnet" in task.model_overrides
       assert task.requirements[0].priority == Priority.CRITICAL
       assert len(task.auto_verify.items) == 1
       assert task.retry.max_attempts == 3

       # Step 2: Implementation (multiple tasks)
       step2 = routine.steps[1]
       assert len(step2.tasks) == 2
       assert step2.tasks[0].id == "T-02"
       assert step2.tasks[1].id == "T-03"
   
   def test_reject_ref_inheritance():
       """CRITICAL: Files with ref/use must be rejected."""
       with pytest.raises(RoutineValidationError) as exc_info:
           load_routine_from_path(FIXTURES / "invalid_with_ref.yaml")
       assert "ref" in str(exc_info.value).lower() or "not supported" in str(exc_info.value).lower()
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_routine_loader.py -v
```

#### Integration Tests
```bash
uv run pytest tests/integration/test_routine_loading.py -v
```

**Expected:** All tests pass, including ref rejection.

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] `load_routine_from_path` function works
- [ ] All error types are raised correctly
- [ ] Test fixtures exist and are valid
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] ref/use rejection works (CRITICAL)

---

## Slice 1.4: State Models

### Goal
Define runtime state models: Run, Step, Task, Attempt, ChecklistItem. These represent execution state, not configuration.

### Prerequisites
- Slice 1.2 complete

### Deliverables

```
src/orchestrator/
├── state/
│   ├── __init__.py
│   └── models.py      # Runtime state Pydantic models
tests/unit/
└── test_state_models.py
```

### Architecture Constraints

1. **Separation of config vs state** - RoutineConfig is the template. Run/Task/etc are runtime state created FROM config.

2. **State models are mutable** - Unlike config models, state changes over time.

3. **IDs are generated, not user-provided** - Use UUID4 for run_id, task instance IDs, etc.

### Implementation Steps

1. Create `src/orchestrator/state/models.py`:
   ```python
   from pydantic import BaseModel, Field
   from datetime import datetime
   from typing import Any
   from uuid import uuid4
   
   from orchestrator.config.enums import (
       RunStatus, TaskStatus, ChecklistStatus, AgentType, RoutineSource, Priority
   )
   
   def generate_id() -> str:
       return str(uuid4())
   
   class ChecklistItem(BaseModel):
       """Runtime state of a single requirement."""
       req_id: str
       desc: str
       priority: Priority
       status: ChecklistStatus = ChecklistStatus.OPEN
       note: str | None = None
       grade: str | None = None
       grade_reason: str | None = None
   
   class AttemptMetrics(BaseModel):
       """Metrics for a single attempt."""
       tokens_read: int = 0
       tokens_write: int = 0
       tokens_cache: int = 0
       duration_ms: int = 0
   
   class Attempt(BaseModel):
       """A single builder→verifier cycle."""
       id: str = Field(default_factory=generate_id)
       attempt_num: int
       started_at: datetime | None = None
       completed_at: datetime | None = None
       builder_prompt: str | None = None
       verifier_prompt: str | None = None
       verifier_comment: str | None = None
       outcome: str | None = None  # "passed", "revision_needed", "failed"
       metrics: AttemptMetrics = Field(default_factory=AttemptMetrics)
   
   class TaskState(BaseModel):
       """Runtime state of a task."""
       id: str = Field(default_factory=generate_id)
       config_id: str  # Links to TaskConfig.id
       status: TaskStatus = TaskStatus.PENDING
       checklist: list[ChecklistItem] = Field(default_factory=list)
       attempts: list[Attempt] = Field(default_factory=list)
       current_attempt: int = 0
       max_attempts: int = 3
   
   class StepState(BaseModel):
       """Runtime state of a step."""
       id: str = Field(default_factory=generate_id)
       config_id: str  # Links to StepConfig.id
       tasks: list[TaskState] = Field(default_factory=list)
       completed: bool = False
   
   class Run(BaseModel):
       """Runtime state of an entire run."""
       id: str = Field(default_factory=generate_id)
       project_id: str
       status: RunStatus = RunStatus.DRAFT
       
       # Routine reference
       routine_id: str | None = None
       routine_sha: str | None = None
       routine_source: RoutineSource | None = None
       
       # Agent configuration
       agent_type: AgentType | None = None
       agent_config: dict[str, Any] = Field(default_factory=dict)
       
       # Worktree
       worktree_enabled: bool = True
       worktree_path: str | None = None
       delete_worktree_on_completion: bool = False
       
       # Config passed to routine
       config: dict[str, Any] = Field(default_factory=dict)
       
       # Runtime state
       steps: list[StepState] = Field(default_factory=list)
       current_step_index: int = 0
       
       # Timestamps
       created_at: datetime = Field(default_factory=datetime.utcnow)
       updated_at: datetime = Field(default_factory=datetime.utcnow)
       started_at: datetime | None = None
       completed_at: datetime | None = None
       
       # Aggregate metrics
       total_tokens_read: int = 0
       total_tokens_write: int = 0
       total_duration_ms: int = 0
   ```

2. Create `tests/unit/test_state_models.py`:
   ```python
   import pytest
   from datetime import datetime
   from orchestrator.state.models import (
       Run, StepState, TaskState, Attempt, ChecklistItem, AttemptMetrics
   )
   from orchestrator.config.enums import (
       RunStatus, TaskStatus, ChecklistStatus, Priority, AgentType
   )
   
   def test_run_default_values():
       run = Run(project_id="test-project")
       assert run.status == RunStatus.DRAFT
       assert run.id is not None  # Auto-generated
       assert len(run.id) == 36  # UUID format
       assert run.worktree_enabled is True
   
   def test_run_with_values():
       run = Run(
           project_id="test-project",
           routine_id="planning",
           agent_type=AgentType.OPENHANDS_LOCAL,
           config={"feature": "auth"},
       )
       assert run.routine_id == "planning"
       assert run.agent_type == AgentType.OPENHANDS_LOCAL
       assert run.config["feature"] == "auth"
   
   def test_task_state_checklist():
       task = TaskState(
           config_id="T-01",
           checklist=[
               ChecklistItem(
                   req_id="R1",
                   desc="Requirement 1",
                   priority=Priority.CRITICAL,
               ),
               ChecklistItem(
                   req_id="R2",
                   desc="Requirement 2",
                   priority=Priority.EXPECTED,
                   status=ChecklistStatus.DONE,
               ),
           ]
       )
       assert len(task.checklist) == 2
       assert task.checklist[0].status == ChecklistStatus.OPEN
       assert task.checklist[1].status == ChecklistStatus.DONE
   
   def test_attempt_metrics():
       attempt = Attempt(
           attempt_num=1,
           metrics=AttemptMetrics(
               tokens_read=1000,
               tokens_write=500,
               duration_ms=5000,
           )
       )
       assert attempt.metrics.tokens_read == 1000
       assert attempt.metrics.duration_ms == 5000
   
   def test_checklist_item_with_grade():
       item = ChecklistItem(
           req_id="R1",
           desc="Test",
           priority=Priority.CRITICAL,
           status=ChecklistStatus.DONE,
           grade="A",
           grade_reason="Well implemented",
       )
       assert item.grade == "A"
       assert item.grade_reason == "Well implemented"
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_state_models.py -v
```

**Expected:** All tests pass.

#### Integration Tests
None for this slice (models are standalone).

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] All state models defined
- [ ] Models generate IDs automatically
- [ ] Default values are correct
- [ ] Unit tests pass
- [ ] Pyright has no errors

---

## Slice 1.5: Run Factory

### Goal
Create runs from routine configs. This bridges configuration to runtime state.

### Prerequisites
- Slice 1.3 complete (routine loading)
- Slice 1.4 complete (state models)

### Deliverables

```
src/orchestrator/
├── state/
│   └── factory.py     # Create Run from RoutineConfig
tests/
├── unit/
│   └── test_run_factory.py
└── integration/
    └── test_run_creation.py
```

### Architecture Constraints

1. **Factory is a pure function** - Takes RoutineConfig, returns Run. No I/O.

2. **Checklist is populated from requirements** - Each requirement becomes a ChecklistItem.

3. **IDs are deterministic in tests** - Inject ID generator for testing.

### Implementation Steps

1. Create `src/orchestrator/state/factory.py`:
   ```python
   from typing import Callable
   from uuid import uuid4
   
   from orchestrator.config.models import RoutineConfig, TaskConfig
   from orchestrator.state.models import (
       Run, StepState, TaskState, ChecklistItem
   )
   from orchestrator.config.enums import RoutineSource
   
   def default_id_generator() -> str:
       return str(uuid4())
   
   def create_checklist_from_requirements(
       task_config: TaskConfig,
   ) -> list[ChecklistItem]:
       """Create checklist items from task requirements."""
       return [
           ChecklistItem(
               req_id=req.id,
               desc=req.desc,
               priority=req.priority,
           )
           for req in task_config.requirements
       ]
   
   def create_task_state(
       task_config: TaskConfig,
       id_generator: Callable[[], str] = default_id_generator,
   ) -> TaskState:
       """Create task state from task config."""
       return TaskState(
           id=id_generator(),
           config_id=task_config.id,
           checklist=create_checklist_from_requirements(task_config),
           max_attempts=task_config.retry.max_attempts,
       )
   
   def create_step_state(
       step_config: StepConfig,
       id_generator: Callable[[], str] = default_id_generator,
   ) -> StepState:
       """Create step state from step config."""
       tasks = [
           create_task_state(task_config, id_generator)
           for task_config in step_config.tasks
       ]

       return StepState(
           id=id_generator(),
           config_id=step_config.id,
           tasks=tasks,
       )
   
   def create_run_from_routine(
       routine: RoutineConfig,
       project_id: str,
       config: dict | None = None,
       routine_source: RoutineSource | None = None,
       routine_sha: str | None = None,
       id_generator: Callable[[], str] = default_id_generator,
   ) -> Run:
       """
       Create a Run instance from a RoutineConfig.
       
       Args:
           routine: The routine configuration
           project_id: ID of the project
           config: Runtime configuration values
           routine_source: Where the routine came from
           routine_sha: Git SHA of the routine
           id_generator: Function to generate IDs (inject for testing)
           
       Returns:
           A new Run in DRAFT status
       """
       steps = [
           create_step_state(step_config, id_generator)
           for step_config in routine.steps
       ]
       
       return Run(
           id=id_generator(),
           project_id=project_id,
           routine_id=routine.id,
           routine_source=routine_source,
           routine_sha=routine_sha,
           config=config or {},
           steps=steps,
       )
   ```

2. Create `tests/unit/test_run_factory.py`:
   ```python
   import pytest
   from orchestrator.config.models import (
       RoutineConfig, StepConfig, TaskConfig, RequirementConfig
   )
   from orchestrator.config.enums import Priority, RoutineSource
   from orchestrator.state.factory import (
       create_run_from_routine,
       create_checklist_from_requirements,
       create_task_state,
   )
   
   @pytest.fixture
   def simple_routine():
       return RoutineConfig(
           id="test-routine",
           name="Test",
           steps=[
               StepConfig(
                   id="S-01",
                   title="Step 1",
                   tasks=[TaskConfig(
                       id="T-01",
                       title="Task 1",
                       task_context="Context",
                       requirements=[
                           RequirementConfig(id="R1", desc="Req 1"),
                           RequirementConfig(id="R2", desc="Req 2", priority=Priority.NICE),
                       ],
                   )],
               ),
           ],
       )
   
   @pytest.fixture
   def sequential_id_generator():
       """Deterministic ID generator for testing."""
       counter = [0]
       def generate():
           counter[0] += 1
           return f"id-{counter[0]}"
       return generate
   
   def test_create_checklist_from_requirements():
       task = TaskConfig(
           id="T1",
           title="Task",
           task_context="Context",
           requirements=[
               RequirementConfig(id="R1", desc="Req 1", priority=Priority.CRITICAL),
               RequirementConfig(id="R2", desc="Req 2", priority=Priority.EXPECTED),
           ],
       )
       checklist = create_checklist_from_requirements(task)
       
       assert len(checklist) == 2
       assert checklist[0].req_id == "R1"
       assert checklist[0].priority == Priority.CRITICAL
       assert checklist[1].priority == Priority.EXPECTED
   
   def test_create_run_basic(simple_routine, sequential_id_generator):
       run = create_run_from_routine(
           routine=simple_routine,
           project_id="proj-1",
           id_generator=sequential_id_generator,
       )
       
       assert run.id == "id-1"
       assert run.project_id == "proj-1"
       assert run.routine_id == "test-routine"
       assert len(run.steps) == 1
       assert run.steps[0].id == "id-2"
       assert len(run.steps[0].tasks) == 1
       assert run.steps[0].tasks[0].id == "id-3"
   
   def test_create_run_with_config(simple_routine):
       run = create_run_from_routine(
           routine=simple_routine,
           project_id="proj-1",
           config={"feature": "auth", "branch": "main"},
       )
       
       assert run.config["feature"] == "auth"
       assert run.config["branch"] == "main"
   
   def test_create_run_with_source(simple_routine):
       run = create_run_from_routine(
           routine=simple_routine,
           project_id="proj-1",
           routine_source=RoutineSource.LOCAL,
           routine_sha="abc123",
       )
       
       assert run.routine_source == RoutineSource.LOCAL
       assert run.routine_sha == "abc123"
   
   def test_checklist_populated(simple_routine):
       run = create_run_from_routine(
           routine=simple_routine,
           project_id="proj-1",
       )
       
       task = run.steps[0].tasks[0]
       assert len(task.checklist) == 2
       assert task.checklist[0].req_id == "R1"
       assert task.checklist[1].req_id == "R2"
   ```

3. Create `tests/integration/test_run_creation.py`:
   ```python
   import pytest
   from pathlib import Path
   from orchestrator.routines.loader import load_routine_from_path
   from orchestrator.state.factory import create_run_from_routine
   from orchestrator.config.enums import RoutineSource, RunStatus
   
   FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"
   
   def test_create_run_from_loaded_routine():
       """Integration: Load routine from file, create run."""
       routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
       
       run = create_run_from_routine(
           routine=routine,
           project_id="test-project",
           config={"feature_name": "authentication"},
           routine_source=RoutineSource.LOCAL,
       )
       
       assert run.routine_id == "complete-routine"
       assert run.status == RunStatus.DRAFT
       assert run.config["feature_name"] == "authentication"
       
       # Verify structure
       assert len(run.steps) == 2
       task = run.steps[0].tasks[0]
       assert task.config_id == "T-01"
       assert len(task.checklist) == 2  # R1 and R2 from fixture
       assert task.max_attempts == 3  # From retry config
       assert len(run.steps[1].tasks) == 2  # T-02 and T-03
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_run_factory.py -v
```

#### Integration Tests
```bash
uv run pytest tests/integration/test_run_creation.py -v
```

**Expected:** All tests pass.

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] `create_run_from_routine` function works
- [ ] Checklist is populated correctly
- [ ] ID generation is injectable
- [ ] Unit tests pass
- [ ] Integration test passes (load → create)

---

## Slice 1.6: Session State Manager

### Goal
Manage run state in memory and persist to JSON file. This is the first slice with I/O.

### Prerequisites
- Slice 1.5 complete

### Deliverables

```
src/orchestrator/
├── state/
│   ├── session.py     # SessionStateManager class
│   └── errors.py      # State-related errors
tests/
├── unit/
│   └── test_session_state.py
└── integration/
    └── test_session_persistence.py
```

### Architecture Constraints

1. **Manager holds state in memory** - File is for persistence, not primary storage
2. **Save is explicit** - No auto-save. Caller decides when to persist.
3. **Async file I/O** - Use aiofiles for non-blocking writes
4. **Inject file path** - No hardcoded paths

### Implementation Steps

1. Create `src/orchestrator/state/errors.py`:
   ```python
   class StateError(Exception):
       """Base class for state errors."""
       pass
   
   class RunNotFoundError(StateError):
       def __init__(self, run_id: str):
           self.run_id = run_id
           super().__init__(f"Run not found: {run_id}")
   
   class TaskNotFoundError(StateError):
       def __init__(self, run_id: str, task_id: str):
           self.run_id = run_id
           self.task_id = task_id
           super().__init__(f"Task {task_id} not found in run {run_id}")
   ```

2. Create `src/orchestrator/state/session.py`:
   ```python
   from pathlib import Path
   import json
   import aiofiles
   from datetime import datetime
   
   from orchestrator.state.models import Run, TaskState, ChecklistItem
   from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
   from orchestrator.config.enums import ChecklistStatus
   
   class SessionStateManager:
       """
       Manages run state in memory with optional file persistence.
       
       Design: State lives in memory. File is for durability across restarts.
       All mutations happen in memory first, then save() persists.
       """
       
       def __init__(self, persist_path: Path | None = None):
           """
           Args:
               persist_path: Optional path to JSON file for persistence.
                            If None, state is memory-only.
           """
           self._persist_path = persist_path
           self._runs: dict[str, Run] = {}
       
       # --- Read operations ---
       
       def get_run(self, run_id: str) -> Run:
           """Get a run by ID."""
           if run_id not in self._runs:
               raise RunNotFoundError(run_id)
           return self._runs[run_id]
       
       def list_runs(self) -> list[Run]:
           """List all runs."""
           return list(self._runs.values())
       
       def get_task(self, run_id: str, task_id: str) -> TaskState:
           """Get a task by run ID and task ID."""
           run = self.get_run(run_id)
           for step in run.steps:
               for task in step.tasks:
                   if task.id == task_id:
                       return task
           raise TaskNotFoundError(run_id, task_id)
       
       # --- Write operations ---
       
       def add_run(self, run: Run) -> None:
           """Add a new run to state."""
           self._runs[run.id] = run
       
       def update_run(self, run: Run) -> None:
           """Update an existing run."""
           if run.id not in self._runs:
               raise RunNotFoundError(run.id)
           run.updated_at = datetime.utcnow()
           self._runs[run.id] = run
       
       def delete_run(self, run_id: str) -> None:
           """Delete a run."""
           if run_id not in self._runs:
               raise RunNotFoundError(run_id)
           del self._runs[run_id]
       
       def update_checklist_item(
           self,
           run_id: str,
           task_id: str,
           req_id: str,
           status: ChecklistStatus,
           note: str | None = None,
       ) -> ChecklistItem:
           """Update a checklist item status."""
           task = self.get_task(run_id, task_id)
           for item in task.checklist:
               if item.req_id == req_id:
                   item.status = status
                   if note is not None:
                       item.note = note
                   return item
           raise ValueError(f"Requirement {req_id} not found in task {task_id}")
       
       # --- Persistence ---
       
       async def save(self) -> None:
           """Persist state to file."""
           if self._persist_path is None:
               return
           
           data = {
               "runs": {
                   run_id: run.model_dump(mode="json")
                   for run_id, run in self._runs.items()
               }
           }
           
           self._persist_path.parent.mkdir(parents=True, exist_ok=True)
           async with aiofiles.open(self._persist_path, "w") as f:
               await f.write(json.dumps(data, indent=2, default=str))
       
       async def load(self) -> None:
           """Load state from file."""
           if self._persist_path is None or not self._persist_path.exists():
               return
           
           async with aiofiles.open(self._persist_path, "r") as f:
               content = await f.read()
           
           data = json.loads(content)
           self._runs = {
               run_id: Run.model_validate(run_data)
               for run_id, run_data in data.get("runs", {}).items()
           }
   ```

3. Create `tests/unit/test_session_state.py`:
   ```python
   import pytest
   from orchestrator.state.session import SessionStateManager
   from orchestrator.state.models import Run, StepState, TaskState, ChecklistItem
   from orchestrator.state.errors import RunNotFoundError, TaskNotFoundError
   from orchestrator.config.enums import ChecklistStatus, Priority
   
   @pytest.fixture
   def manager():
       return SessionStateManager()  # Memory-only
   
   @pytest.fixture
   def sample_run():
       return Run(
           id="run-1",
           project_id="proj-1",
           steps=[
               StepState(
                   id="step-1",
                   config_id="S-01",
                   tasks=[
                       TaskState(
                           id="task-1",
                           config_id="T-01",
                           checklist=[
                               ChecklistItem(
                                   req_id="R1",
                                   desc="Requirement 1",
                                   priority=Priority.CRITICAL,
                               ),
                           ],
                       ),
                   ],
               ),
           ],
       )
   
   def test_add_and_get_run(manager, sample_run):
       manager.add_run(sample_run)
       retrieved = manager.get_run("run-1")
       assert retrieved.id == "run-1"
   
   def test_get_nonexistent_run(manager):
       with pytest.raises(RunNotFoundError):
           manager.get_run("nonexistent")
   
   def test_list_runs(manager, sample_run):
       manager.add_run(sample_run)
       runs = manager.list_runs()
       assert len(runs) == 1
   
   def test_get_task(manager, sample_run):
       manager.add_run(sample_run)
       task = manager.get_task("run-1", "task-1")
       assert task.config_id == "T-01"
   
   def test_get_nonexistent_task(manager, sample_run):
       manager.add_run(sample_run)
       with pytest.raises(TaskNotFoundError):
           manager.get_task("run-1", "nonexistent")
   
   def test_update_checklist_item(manager, sample_run):
       manager.add_run(sample_run)
       item = manager.update_checklist_item(
           run_id="run-1",
           task_id="task-1",
           req_id="R1",
           status=ChecklistStatus.DONE,
           note="Completed successfully",
       )
       assert item.status == ChecklistStatus.DONE
       assert item.note == "Completed successfully"
   
   def test_delete_run(manager, sample_run):
       manager.add_run(sample_run)
       manager.delete_run("run-1")
       with pytest.raises(RunNotFoundError):
           manager.get_run("run-1")
   ```

4. Create `tests/integration/test_session_persistence.py`:
   ```python
   import pytest
   from pathlib import Path
   from orchestrator.state.session import SessionStateManager
   from orchestrator.state.models import Run, StepState, TaskState
   from orchestrator.config.enums import RunStatus
   
   @pytest.fixture
   def persist_path(tmp_path):
       return tmp_path / "state" / "session.json"
   
   @pytest.mark.asyncio
   async def test_save_and_load(persist_path):
       # Create and save
       manager1 = SessionStateManager(persist_path)
       run = Run(
           id="run-1",
           project_id="proj-1",
           steps=[StepState(id="s1", config_id="S-01", tasks=[])],
       )
       manager1.add_run(run)
       await manager1.save()
       
       # Load in new manager
       manager2 = SessionStateManager(persist_path)
       await manager2.load()
       
       retrieved = manager2.get_run("run-1")
       assert retrieved.id == "run-1"
       assert retrieved.project_id == "proj-1"
       assert len(retrieved.steps) == 1
   
   @pytest.mark.asyncio
   async def test_save_creates_directory(tmp_path):
       deep_path = tmp_path / "a" / "b" / "c" / "session.json"
       manager = SessionStateManager(deep_path)
       manager.add_run(Run(id="r1", project_id="p1"))
       await manager.save()
       
       assert deep_path.exists()
   
   @pytest.mark.asyncio
   async def test_load_empty_file(tmp_path):
       path = tmp_path / "empty.json"
       path.write_text("{}")
       
       manager = SessionStateManager(path)
       await manager.load()
       
       assert len(manager.list_runs()) == 0
   
   @pytest.mark.asyncio
   async def test_load_nonexistent_file(tmp_path):
       path = tmp_path / "nonexistent.json"
       manager = SessionStateManager(path)
       await manager.load()  # Should not raise
       assert len(manager.list_runs()) == 0
   ```

### Verification

#### Unit Tests
```bash
uv run pytest tests/unit/test_session_state.py -v
```

#### Integration Tests
```bash
uv run pytest tests/integration/test_session_persistence.py -v
```

**Expected:** All tests pass.

#### E2E Tests
None for this slice.

### Definition of Done
- [ ] SessionStateManager class works
- [ ] CRUD operations work correctly
- [ ] Persistence to JSON works
- [ ] Async file I/O used
- [ ] Unit tests pass
- [ ] Integration tests pass

---

## Phase 1 Milestone Verification

After completing all Phase 1 slices, verify the entire phase works together:

```bash
# All tests pass
uv run pytest tests/ -v

# Type checking passes
uv run pyright src/

# Linting passes
uv run ruff check src/

# Manual verification: Load routine and create run
uv run python -c "
from pathlib import Path
from orchestrator.routines.loader import load_routine_from_path
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.session import SessionStateManager
import asyncio

async def main():
    # Load routine
    routine = load_routine_from_path(Path('tests/fixtures/routines/valid_complete.yaml'))
    print(f'Loaded routine: {routine.id}')
    
    # Create run
    run = create_run_from_routine(
        routine=routine,
        project_id='test-project',
        config={'feature_name': 'auth'},
    )
    print(f'Created run: {run.id}')
    print(f'Steps: {len(run.steps)}')
    print(f'Tasks in first step: {len(run.steps[0].tasks)}')
    print(f'Checklist items: {len(run.steps[0].tasks[0].checklist)}')
    
    # Persist
    manager = SessionStateManager(Path('/tmp/test-state.json'))
    manager.add_run(run)
    await manager.save()
    print('Saved to /tmp/test-state.json')

asyncio.run(main())
"
```

**Expected output:**
```
Loaded routine: complete-routine
Created run: <uuid>
Steps: 2
Tasks in first step: 1
Checklist items: 2
Saved to /tmp/test-state.json
```

If this works, Phase 1 is complete. Proceed to Phase 2.
