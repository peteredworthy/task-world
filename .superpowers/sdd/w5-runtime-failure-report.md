W5 runtime/environment failure typed projection slice report

Status
- Done.

Summary
- Added typed `EnvironmentFailureProjection` model and exported it from `orchestrator.graph`.
- Switched `GraphProjection["environment_failures"]` from raw dict payloads to typed projection instances.
- Updated reducer fold logic to validate and store typed environment-failure projections while preserving existing event payload JSON.
- Updated projection checkpoint serialization/deserialization to round-trip the typed field.
- Kept malformed `environment_failure_accepted` payload handling tolerant by skipping invalid entries instead of raising or persisting raw dicts.

Files changed
- `/Users/peter/code/task-world/src/orchestrator/graph/models.py`
- `/Users/peter/code/task-world/src/orchestrator/graph/projections.py`
- `/Users/peter/code/task-world/src/orchestrator/graph/__init__.py`

TDD evidence
- RED (owner-provided prior failure): `uv run pytest tests/unit/test_graph_projections.py -q`
  - Failed at import because `EnvironmentFailureProjection` was missing.
- GREEN (post-implementation):
  - Command: `uv run pytest tests/unit/test_graph_projections.py -q`
  - Result: `80 passed in 1.47s`

Notes
- Historical accepted environment-failure events that only provide a string `reason` still project successfully.
- Derived environment-failure reasons now respect top-level classifications when legacy payloads place command/stderr details under `value`.

Owner follow-up
- Added a missing-reason regression after review found the typed model required `reason` too strictly.
- Changed `EnvironmentFailureProjection.reason` to `str | None = None` so missing/None reasons preserve the old projection entry while malformed non-string reasons are still skipped.
- Carried `EnvironmentFailureProjection` through `GraphProjectionSnapshot` instead of downcasting it to `dict[str, Any]`.
- Fixed planner outstanding-failure serialization to use `model_dump(mode="json")`, preserving the old sparse packet shape instead of leaking optional `None` fields from `dict(BaseModel)`.
- Avoided synthetic `payload["position"]` assignment in the reducer so the static payload-field allowlist guard does not treat `event.position` as a persisted payload dependency.

Owner verification
- `uv run pytest tests/unit/test_graph_projections.py -q` -> `81 passed in 1.29s`
- `uv run pyright src/orchestrator/graph src/orchestrator/workflow/graph_driver.py` -> `0 errors, 0 warnings, 0 informations`
- `uv run ruff check src/orchestrator/graph/models.py src/orchestrator/graph/projections.py src/orchestrator/graph/__init__.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_projections.py tests/unit/test_graph_driver_logic.py` -> `All checks passed!`
- `uv run pytest tests/unit/test_graph_models.py tests/unit/test_graph_projections.py tests/unit/test_projectors.py tests/unit/test_command_handlers.py tests/unit/test_graph_driver_logic.py tests/integration/test_graph_dynamic_e2e.py tests/integration/test_graph_event_store.py -q` -> `266 passed, 3 warnings in 17.15s`
- `uv run pytest tests/unit/test_graph_planner_packet.py::test_planner_packet_includes_generation_frontier_evidence_and_rejections tests/unit/test_graph_payload_field_allowlists.py::test_graph_projection_payload_fields_cover_the_reduce_event_fold -q` -> `2 passed in 2.05s`
- `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime/prompts.py src/orchestrator/workflow/graph_driver.py` -> `0 errors, 0 warnings, 0 informations`
- `uv run ruff check src/orchestrator/graph/models.py src/orchestrator/graph/projections.py src/orchestrator/graph/__init__.py src/orchestrator/graph_runtime/prompts.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_projections.py tests/unit/test_graph_driver_logic.py` -> `All checks passed!`
- `uv run pytest tests/unit/test_graph*.py tests/integration/test_graph*.py -q` -> `749 passed in 24.33s`
