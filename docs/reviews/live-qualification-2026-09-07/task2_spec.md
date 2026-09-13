# Qualification trial 2: JSONL-to-CSV conversion

Build `examples/qualification/jsonl_to_csv.py`, real tests in
`tests/unit/test_qualification_jsonl_to_csv.py`, and usage documentation. Limit
changes to these new utility/test paths and their README; do not modify server
code or existing checks. Use the supported sequential adaptive workflow with
reviewed planning, one pure-function batch, and a second CLI/documentation batch
planned from accepted evidence. Fresh independent verification and the unchanged
project gate are required.

Export pure `jsonl_to_csv(text: str, columns: tuple[str, ...]) -> str` and a
domain-specific `ConversionError`. Parse UTF-8 JSON objects one per line,
ignoring blank lines. Reject malformed/non-object lines, duplicate columns,
empty columns, and nonstandard numbers with useful diagnostics. Emit an ordered
header even for empty input; missing keys are empty cells; strings are unquoted
data before CSV escaping; booleans/numbers/null/arrays/objects use compact JSON
with sorted object keys, preserved Unicode, and no NaN. Use LF row endings and
standards-compliant quoting. Column names refer to top-level keys literally.

CLI: `uv run python examples/qualification/jsonl_to_csv.py INPUT OUTPUT --columns
COL1 COL2`. Handle paths with spaces. Validate all input before touching OUTPUT;
invalid input must preserve a pre-existing output file. Exit 0 on success and 2
on invalid input, decode, or I/O errors with concise stderr and no traceback.
Keep logic pure and I/O separate, following repository rules. Tests must cover
commas, quotes, embedded newlines, nested values, blank lines, missing keys,
empty input, invalid records, and preserving existing output on failure.

Do not merge, deploy, start servers, weaken checks, or manufacture failures.
Correct real failed candidates through the normal runtime when necessary.
