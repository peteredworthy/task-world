Task: W5 runtime/environment failure typed projection slice

Context:
- W5 is an incremental typed payload cleanup for the dynamic graph kernel.
- Callback idempotency projection is already typed in this tree.
- The next small slice is `environment_failures`, currently stored as raw `dict[str, Any]` in `GraphProjection`.

Requirements:
- Add a typed projection model for environment/runtime failure facts, suitable for storing in `GraphProjection["environment_failures"]`.
- `reduce_event` must parse once at fold time and store model instances, not raw dicts.
- Checkpoint serialization/deserialization must round-trip the typed field.
- Malformed historical payloads must be tolerated by skipping the projection entry rather than raising or storing a raw dict.
- Preserve existing event JSON schema and existing observable task-state/final-blocker behavior.
- Do not broaden the slice to unrelated projection maps.

Acceptance target:
- `uv run pytest tests/unit/test_graph_projections.py -q`
- The owner already added RED tests in `tests/unit/test_graph_projections.py` for:
  - typed environment failure projection,
  - checkpoint round-trip,
  - malformed payload tolerance.

Constraints:
- Follow AGENTS.md: no mocks, use `uv run`, no bare Python, no destructive git commands.
- Do not run git commands or create commits from the main working tree.
- Import across top-level modules only through public APIs.
