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


Run the unchanged acceptance command `uv run python /private/tmp/qualification-20260907/task1_oracle.py`. Use a fixed single builder/check/verifier cycle. Do not inspect or edit the acceptance script. Do not edit orchestrator server code, existing tests or gate configuration. Do not merge, deploy, or start servers. Implement from this specification without reading sibling worktrees. CLI subprocess tests belong under tests/integration/. Submit via the normal orchestrator callback and let fresh-context verification grade the actual requirements.
