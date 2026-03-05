# Step 14: Multi-file routine definitions (A17)

## Milestone
M4: Schema & Architecture Extensions

## Purpose
Support routines split across multiple YAML files. A root `routine.yaml` references step files (`step-01.yaml`, etc.), and the loader resolves references, validates all files exist, and assembles the complete routine. This enables better organization for large routines.

## Prerequisites / Dependencies
- None directly. The loader (`loader.py`) and models (`models.py`) are the extension points.
- Independent of M1-M3 steps.

## Functional Contract

### Inputs
- Root `routine.yaml` with steps that may include a `file` field:
  ```yaml
  steps:
    - file: steps/step-01.yaml
    - file: steps/step-02.yaml
    - name: inline-step
      tasks: [...]
  ```

### Outputs
- **Success:** Complete `RoutineConfig` assembled from root + referenced files
- **Validation failure (missing file):** `RoutineValidationError` with missing path and referencing step
- **Validation failure (overlap):** If a step specifies `file` AND other step fields (name, tasks, etc.), validation fails — no overlap allowed per clarification decision

### Errors
- `RoutineValidationError` — referenced step file does not exist (includes missing path and step index)
- `ValueError` — step has both `file` and other fields (ambiguous definition)

### Schema Addition
```python
class StepConfig(BaseModel):
    file: str | None = None  # relative path to step YAML file
```

### Loader Changes
1. Parse root `routine.yaml`
2. For each step with `file` field, resolve path relative to routine directory
3. Validate referenced file exists
4. Load and parse referenced YAML as complete step definition
5. Assemble final `RoutineConfig`

## Files Modified
- `src/orchestrator/config/models.py` — add `file` field to `StepConfig`, add overlap validation
- `src/orchestrator/config/loader.py` — multi-file resolution logic

## Verification Strategy
- **Unit test:** Loader resolves step file references correctly.
- **Unit test:** Missing step file raises `RoutineValidationError` with descriptive message.
- **Unit test:** Step with `file` AND other fields raises validation error.
- **Unit test:** Inline steps (no `file`) continue to work unchanged.
- **Integration test:** Full routine load from multi-file structure.
- **New test file:** `tests/unit/test_loader_multifile.py`
- **Regression:** Existing loader tests pass.
