# Feedback task: explain a blocked run through public APIs

Create a small read-only developer utility at
`examples/recovery/run_diagnostic.py`, real tests under
`tests/unit/test_recovery_run_diagnostic.py` and
`tests/integration/test_recovery_run_diagnostic_cli.py`, and concise usage in
`examples/recovery/README.md`. Do not modify orchestrator server code, existing
tests, gates, database, or run state. Use Luna and one fixed builder/check/verifier
attempt. Do not merge, deploy, or start the orchestrator server.

The utility must help an operator understand the original cause when the run
summary only says that a graph node failed. Keep it small: no new framework,
dashboard, background monitor, repair endpoint, or inferred recovery commands.

Public contract:

1. Export Pydantic models `FailureDetail` and `RunDiagnostic` and pure
   `build_diagnostic(run: dict, graph: dict | None,
   node_details: tuple[dict, ...], unavailable: tuple[str, ...] = ())` returning
   `RunDiagnostic`. `FailureDetail` has `node_id`, nullable `reason`, and nullable
   `event_position`. `RunDiagnostic` has `run_id`, `status`, nullable
   `pause_reason`, nullable `summary_error`, `failures`, and `unavailable`.
   Validate malformed input at this boundary with a typed error; do not fabricate
   success or silently use the wrong run's node details.
2. Enumerate failed graph nodes in stable node-ID order. For each, prefer the
   earliest nonempty runtime failure `reason` from `agent_died` or a failed
   `node_state_changed` entry in `callback_history`/`events`. Deduplicate overlap
   by event identity/position. Retain the exact graph position; absent evidence
   yields null and an unavailable diagnostic. Preserve the run's summary error
   separately. This incident must expose
   `check command_definition requires non-empty argv or cmd` at position 486.
3. CLI: `uv run python examples/recovery/run_diagnostic.py RUN_UUID
   --base-url http://localhost:8000`. Validate the UUID and HTTP(S) base URL.
   Fetch only public GET endpoints: run, graph for a graph-backed run, and at
   most ten failed-node detail pages. URL-encode node path segments. Use async
   HTTP with bounded connect/read timeouts, bounded response bytes, no automatic
   retry, and no redirects. Report omitted nodes as unavailable. A non-graph
   run needs only its run response.
4. Print exactly one JSON diagnostic to stdout. Exit 0 for a fully read report
   (even if the reported run failed), 1 for a partial report, 2 for usage or
   inability to fetch/validate the run. Concise stderr diagnostics, no secrets
   or tracebacks. A failed or missing graph/node endpoint must produce partial
   evidence rather than an empty healthy-looking report.
5. Unit tests use real data and pure functions; integration tests use a real
   local HTTP fixture server and real subprocess CLI. Cover original-cause
   selection, duplicate events, missing/partial data, wrong-run evidence,
   invalid UUID/base URL, unavailable server, oversized responses, failed-node
   cap, and a legacy run. No patch, MagicMock, monkeypatching, or credentials.
6. Run focused tests and the unchanged submission checks. Then use the actual
   CLI against existing run `d20ff4dd-9cd1-4f29-9df1-d344a0582907` through the
   existing server. It must report the exact empty-command cause and position
   if that readback is available. If unavailable, record partial evidence and
   do not claim live validation. Submit for independent verification.

Accept only if the real utility explains the incident, focused tests pass, and
the independent verifier checks the stated behavior and scope. Any expansion
outside this contract needs a new task; do not turn the utility into a server
repair project.
