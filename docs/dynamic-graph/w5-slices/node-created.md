# `node_created` Typed Payload Slice

`node_created` is produced by compiler seeding and by command paths for accepted
patch operations, planner-budget gates, failed-check/failed-verification
recovery, final-invariant checks, and invalid-test appeals. Every producer must
validate and JSON-dump `NodeCreatedPayload` before constructing the event.

The payload has fixed fields for node identity/kind/state/role; membership and
attempt/candidate indexes; authority claims/actions/preconditions; planner
session, generation, and chain data; gate/request prompts; flexible request and
command-definition metadata; recovery lineage; and typed input/output ports.
It inherits the single `GraphEventPayloadBase.extra` map. Unknown or malformed
legacy top-level values move into that map rather than being rejected or lost.
Sparse historical events still skip projection when `node_id` is invalid, and
all existing membership/authority fallbacks remain.

Reducer coverage includes node state/kind/role/task/attempt/candidate indexes,
authority indexes, planner generation/session/region indexes, recovery lineage,
gate/request/review views, command definitions, blocked-requirement metadata,
and seeded planner-chain labels. `command_definition`, request records, and
request metadata stay flexible; W5 does not deep-type them.

Compact replay must retain every reducer-read field in all four store
allowlists: graph projection, light graph, summary rebuild, and node detail.
Real SQLite tests cover JSON extraction (including boolean normalization) and
assert compact projections match full replay. No projection schema bump is
needed unless the stored `GraphProjection` shape or reducer semantics change.

Acceptance requires the five named plan tests, compiler and command producer
coverage, full-shape normalization, corpus parity, focused SQLite compact
parity, the graph/allowlist suites, Ruff, Pyright, and a fresh independent
verification of producer parity and reducer-read retention.
