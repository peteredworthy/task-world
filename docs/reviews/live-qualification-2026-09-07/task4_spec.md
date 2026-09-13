# Qualification trial 4: run-duration summaries

Build `examples/qualification/duration_summary.py`, real tests at
`tests/unit/test_qualification_duration_summary.py`, and usage documentation.
Only change these new utility/test paths and their README. Use the supported
sequential adaptive profile with reviewed planning, pure duration calculation
as the first batch, then CLI/tests/documentation from accepted evidence. Keep
the existing project gate and use independent verification.

Input is a JSON array of records with nonempty `run_id`, `event` equal to
`start` or `end`, and an ISO-8601 `timestamp` with explicit timezone. Validate
with Pydantic. Export pure `summarize_durations(records)` returning typed records
sorted by run ID with `run_id`, `started_at`, `ended_at`, `duration_ms`, and
`status` (`completed` or `unfinished`). Normalize timestamps to UTC. An ended
run needs a start; an end before its start is invalid. Identical duplicate
events count once; conflicting duplicate starts/ends are invalid. Event order
must not affect results. Unfinished runs have null end/duration and never infer
the current time. Reject precision finer than milliseconds rather than silently
rounding; duration_ms is an exact integer.

CLI: `uv run python examples/qualification/duration_summary.py INPUT`, printing
one JSON array. Exit 0 on success and 2 with concise stderr and no traceback on
invalid input or I/O. Test interleaved records, UTC offsets, equivalent duplicate
timestamps, unfinished runs, missing starts, naive times, conflicting duplicates,
sub-millisecond times, and real files. Use `DurationInputError` for domain errors.

The operator may perform a controlled server restart during this trial; agents
must not start/restart servers or manage run state themselves. Do not modify
server code, existing tests, or production data. No mocking, merging, deployment,
or deliberate failures. Follow normal runtime corrections on actual failures.
