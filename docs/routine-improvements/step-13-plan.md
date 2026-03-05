# Step 13: Task complexity labeling (A16)

## Milestone
M4: Schema & Architecture Extensions

## Purpose
Add a `complexity` field to task config that labels tasks as `simple` or `standard`. Simple tasks are atomic and suitable for local/cheaper LLMs. This is diagnostic metadata only — no automatic behavior changes. Future work may use this for agent routing.

## Prerequisites / Dependencies
- None. Purely additive schema change.

## Functional Contract

### Inputs
- `TaskConfig` with optional `complexity` field

### Outputs
- `complexity` field stored on task config with value `"simple"` or `"standard"`
- Default: `"standard"`

### Errors
- Validation error if value is not one of `"simple"` or `"standard"`

### Schema Addition
```python
class TaskConfig(BaseModel):
    complexity: Literal["simple", "standard"] = "standard"
```

## Files Modified
- `src/orchestrator/config/models.py` — add `complexity` field to `TaskConfig`
- `src/orchestrator/config/enums.py` — optionally add `Complexity` enum (or use `Literal` directly)

## Verification Strategy
- **Unit test:** `TaskConfig` accepts `complexity: "simple"` and `complexity: "standard"`.
- **Unit test:** Default value is `"standard"` when not specified.
- **Unit test:** Invalid value (e.g., `"complex"`) raises validation error.
- **Regression:** Existing TaskConfig tests pass.
