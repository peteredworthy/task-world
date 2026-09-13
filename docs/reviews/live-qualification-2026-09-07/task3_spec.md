# Qualification trial 3: usage aggregation

Build `examples/qualification/usage_summary.py`, real tests in
`tests/unit/test_qualification_usage_summary.py`, and usage documentation.
Only change these new utility/test paths and their README. Do not modify server
code, existing checks, or production data. Use two bounded sequential adaptive
batches (pure aggregation; then CLI and real-file tests), independently reviewed
planning, fresh verification, and the unchanged project submission gate.

Input is a JSON array of usage objects: `usage_id` and `model` are nonempty
strings; `input_tokens`, `output_tokens`, and `cached_input_tokens` are optional
nonnegative integer counts (missing or null means unknown, not zero). Booleans
and floats are not integer counts. Cached input is a subset of input and must
not exceed known input. Validate using Pydantic.

Export pure `aggregate_usage(records)` returning typed Pydantic model summaries
sorted by model. Each summary has `model`, `record_count`, `input_tokens`,
`output_tokens`, `cached_input_tokens`, and `total_tokens`. Identical duplicate
usage IDs count once; conflicting duplicate IDs raise `UsageInputError`, even
across models. If any unique record lacks a particular count, that model's
aggregate for that count is null. `total_tokens` is input plus output only when
both are known; never add cached input again. Empty input yields no summaries.

CLI: `uv run python examples/qualification/usage_summary.py INPUT`, printing
one JSON array of summaries to stdout. Exit 0 on success; 2 with concise stderr
and no traceback on input/decode/I/O errors. Test unknown versus zero, cached
input accounting, duplicates, conflicting IDs, order independence, empty input,
multiple models, and real CLI files. No mocking or production journal reads.
Do not merge, deploy, start servers, or manufacture a corrective cycle.
