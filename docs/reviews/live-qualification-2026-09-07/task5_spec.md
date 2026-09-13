# Qualification trial 5: compare qualification results

Build `examples/qualification/compare_results.py`, real tests at
`tests/unit/test_qualification_compare_results.py`, and usage documentation.
Restrict changes to those new utility/test paths and their README. Use the
supported two-batch sequential workflow (pure comparison then CLI/integration),
independently reviewed planning, unchanged project gate, and fresh verification.

Each input JSON document has `schema_version: 1`, `duration_unit: "ms"`,
`currency: "USD"`, and `runs`. Each run has unique nonempty `run_id`, status
(`completed`, `failed`, `paused`, or `cancelled`), boolean `accepted`, nonnegative
integer `interventions`, nullable nonnegative integer `tokens` and `duration_ms`,
and nullable nonnegative decimal-dollar `cost_usd` represented as a string.
Reject unknown versions/units/currency, duplicate IDs, invalid numeric types,
negative values, nonfinite costs, and accepted non-completed runs. Use Pydantic
validation, decimal arithmetic for money, and `ComparisonInputError`.

Export pure `compare_results(baseline, candidate)` returning a typed Pydantic
report containing `baseline`, `candidate`, and `delta`. Each side summarizes
`attempted`, `completed`, `accepted`, `interventions`, `tokens`, `duration_ms`,
and `cost_usd`. Count every run, including failures/incomplete runs. If any
record lacks a token, duration, or cost value, that total is null. Empty known
totals are zero. Monetary totals are decimal strings; do not estimate missing
costs. Delta is candidate minus baseline for each field and null when either
side is unknown. Output order must be deterministic.

CLI: `uv run python examples/qualification/compare_results.py BASELINE CANDIDATE`
prints one JSON report; exit 0 on success or 2 with concise stderr and no
traceback on input/I/O failure. Cover failures and incomplete trials, missing
versus zero totals, exact decimal arithmetic, signed deltas, malformed inputs,
order independence, and real CLI files. No mocking, server-code edits, production
data reads, merging, deployment, or manufactured correction evidence.
