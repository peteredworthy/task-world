# Requirement and Evidence Event Payload Slice

## Scope

Type the produced `requirement_revision_recorded` and
`support_evidence_recorded` payloads and the replay-only aliases
`requirement_amended`, `requirement_revision_proposed`,
`support_edge_recorded`, `authority_resolution_recorded`,
`authority_resolved`, and `requirement_revision_authorized`.

## Compatibility surface

- Requirement revisions retain requirement, revision/version, proposal, and
  patch identifier aliases; classification aliases; strict authority and
  behavior booleans; prior-version metadata; and nested legacy requirement
  identity.
- Support evidence retains `support_id`/`edge_id` and
  `requirement_version_id`/`version_id` aliases plus status, stale reason, and
  confidence.
- Authority resolutions retain every identifier used to resolve a revision.
- Invalid typed scalars and unknown legacy top-level keys move under the one
  `extra` map. They are not silently coerced or discarded.
- Malformed historical events remain skippable and sparse historical events
  keep the existing reducer defaults.

## Reducer paths

Parse typed payloads both in `reduce_event` helpers and in the separate
full-history authority-revision blocker scan. Validation strengthening must
continue to stale support attached to prior requirement versions. No
projection shape or reducer semantic change is intended, so the projection
schema version must remain unchanged.

## Acceptance

- The seven named unit tests in
  `tests/unit/test_requirement_evidence_event_payloads.py` pass.
- Fixture corpus replay parity, graph projection/allowlist tests, the complete
  graph test selection, Ruff, and Pyright pass.
- Producers emit payloads accepted by the new models with no unknown
  top-level keys.
