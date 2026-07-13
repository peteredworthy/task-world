# W5 Task 11 — Complete Reads Report

Status: complete. Committed as `cd795d576` after independent PASS.

- Strict projection models carry complete event payloads instead of partial reconstructed dictionaries.
- The four field allowlists and their partial JSON extraction/reconstruction paths were deleted through the `complete_reads` LibCST codemod.
- Complete payloads are retained in storage. All four named readers delegate to catalog-backed `read_run()` hydration; the API applies summary presentation only after hydration.
- The retired allowlist guard test and dependent compact-allowlist unit assertions were deleted. D1–D6 legacy replay code remains untouched for Task13.
- Red evidence: the new complete-payload reader parity test failed against the prior partial dictionary reader. Green evidence: it passed after the codemod cutover.
- Independent verifier PASS:
  - Mandatory task-focused parity suite: **190 passed**.
  - Hydrated-consumer and tracked-profiler suite: **17 passed**.
  - Fixture corpus: **7 passed**.
  - Broad graph suite: **1,025 passed**.
  - `scripts/check_graph_payload_architecture.py`, complete-reads codemod
    `--assert-clean`, and complete-reads AST inventory: passed.
  - Ruff check: passed; format check: **720 files already formatted**.
  - Full-repository Pyright: **0 errors**.
  - `git diff --check`: passed.
  - Mandatory full suite: **4,964 passed, 5 skipped, 3 warnings**.
  - Catalog baseline: **44 events / 23 commands**.
  - Commit hooks: green.
- Deferred Compatibility Cleanup Register entries D1-D6 remain assigned to Task13.
- No database files or staged continuation-prompt content were modified. The pre-existing staged continuation prompt remains untouched.

## Measurement Slice (2026-07-13)

The tracked profiler instantiates `GraphEventStore` with
`build_graph_catalog()`, loads explicit payloads from the tracked
`tests/unit/graph_catalog_samples.py` source, and validates generated payloads
through their owning catalog specifications. `read_run` is the full-read
baseline; the four semantic read entry points are the complete-read comparison.

Exact commands:

```text
/usr/bin/time -l uv run python scripts/profile_graph_readback.py --events 300 --heavy-every 2 --payload-kb 64 --iterations 5
/usr/bin/time -l uv run python scripts/profile_graph_readback.py --events 1000 --heavy-every 2 --payload-kb 128 --iterations 3
```

Wall time includes read and compact JSON payload serialization. Peak allocated
memory is the median `tracemalloc` peak for the same operation. The wall and
RSS measurements below are builder measurements; the independent verifier
reproduced payload bytes, allocated peaks, and parity separately.

Fixture-scale profile (`300` stored rows, `64 KiB` heavy payload every second
row, five samples):

| Read path | Median wall (ms) | Rows | Serialized payload bytes | Median peak allocated bytes |
|---|---:|---:|---:|---:|
| `read_run` baseline | 134.300 | 300 | 19,731,738 | 60,309,546 |
| `read_run_light` | 130.933 | 300 | 19,731,738 | 60,305,138 |
| `read_run_summary_rebuild` | 134.579 | 300 | 19,731,738 | 60,305,162 |
| `read_run_projection` | 131.563 | 300 | 19,731,738 | 60,305,138 |
| `read_run_node_detail` | 131.732 | 300 | 19,731,738 | 60,304,850 |

The fixture-scale builder workload completed in `3,942.652 ms`; the complete
process completed in `4.94 s` real time with `1,085,685,760` bytes maximum
resident set size reported by `/usr/bin/time -l` (the profiler sampled
`1,085,669,376` bytes before final output).

Representative generated profile (`1,000` stored rows, `128 KiB` heavy payload
every second row, three samples):

| Read path | Median wall (ms) | Rows | Serialized payload bytes | Median peak allocated bytes |
|---|---:|---:|---:|---:|
| `read_run` baseline | 758.873 | 1,000 | 131,308,839 | 397,744,576 |
| `read_run_light` | 758.221 | 1,000 | 131,308,839 | 397,652,704 |
| `read_run_summary_rebuild` | 762.158 | 1,000 | 131,308,839 | 397,652,544 |
| `read_run_projection` | 703.884 | 1,000 | 131,308,839 | 397,652,280 |
| `read_run_node_detail` | 694.720 | 1,000 | 131,308,839 | 397,651,584 |

The generated builder workload completed in `14,925.970 ms`; the complete
process completed in `15.97 s` real time with `4,450,861,056` bytes maximum
resident set size reported by `/usr/bin/time -l` (the profiler sampled
`4,450,844,672` bytes before final output).

Independent reproduction using the exact tracked commands above reported:
- 300 rows: all five readers returned `19,731,738` serialized payload bytes;
  median allocated peaks ranged from `60,304,850` to `60,309,546` bytes;
  parity was true for every semantic reader.
- 1,000 rows: all five readers returned `131,308,839` serialized payload bytes;
  median allocated peaks ranged from `397,651,584` to `397,744,576` bytes;
  parity was true for every semantic reader.
