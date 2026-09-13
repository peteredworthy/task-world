# Qualification trial 1: JSONL validation utility

Implement a standalone developer utility at
`examples/qualification/jsonl_validator.py` plus real unit tests under
`tests/unit/test_qualification_jsonl_validator.py` and concise usage documentation
at `examples/qualification/README.md`. This is a real bounded feature delivered
in the run worktree. Do not modify orchestrator server code, existing tests,
existing project gate configuration, or operator-owned acceptance checks.

Required public contract:

1. Export a Pydantic `ValidationIssue` with `line_number: int` (one-based physical
   input line) and `reason: Literal["invalid_json", "non_object"]`.
2. Export pure `validate_jsonl(text: str) -> tuple[ValidationIssue, ...]`.
   Ignore whitespace-only lines; accept JSON objects including Unicode values;
   collect every invalid line in input order. Invalid JSON gets `invalid_json`;
   valid arrays, strings, numbers, booleans, and null get `non_object`.
   Reject nonstandard NaN and Infinity values as invalid JSON. Empty input is valid.
3. CLI: `uv run python examples/qualification/jsonl_validator.py INPUT_PATH`.
   Read UTF-8, support spaces in paths, print exactly one JSON object to stdout:
   `{"valid": true|false, "issues": [{"line_number": N, "reason": "..."}]}`.
   Exit 0 for valid input, 1 for validation failures, 2 for file/decode/usage
   errors. I/O errors must have concise stderr diagnostics without tracebacks.
4. Test empty input, blank lines, Unicode, CRLF, multiple malformed and non-object
   lines, nonstandard numbers, and real CLI file/error paths. No mocking.
5. Keep logic pure and I/O separate; follow repository Python/formatting rules.
   Do not delete or weaken any existing check. Keep the implementation small.

Use the supported sequential adaptive workflow. First discover relevant project
conventions and produce an independently reviewed implementation plan. Deliver
the pure validator and behavior tests as one bounded batch, then plan CLI,
real-file integration tests, and documentation using accepted first-batch
evidence. The first batch's checks should cover its own scope; the complete
acceptance command below is authoritative for final completion.

Final acceptance command (operator-owned, must not be edited):

`uv run python /private/tmp/qualification-20260907/task1_oracle.py`

The unchanged repository submission gate must also pass. Fresh-context
verification must assess actual requirements and bound candidate evidence. Use
normal runtime correction when a real check or verification fails; do not
deliberately introduce errors, fake grades, or claim a correction that did not
happen. Do not merge, deploy, or start servers. Submit an independently verified
candidate in the run worktree.
