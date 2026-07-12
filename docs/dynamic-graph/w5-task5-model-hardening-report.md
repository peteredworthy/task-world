# W5 Task 5 Model-Hardening Follow-up Report

Status: complete. Independently verified and committed as `d12908002`.

## Confirmed file-state producer boundary repair

`PathClassification.to_record()` emits canonical file-state entry fields
including `source`, `size_bytes`, and `entropy`. The independent strict
`StrictFileEntry` now declares those fields explicitly. It remains frozen,
strict, and `extra="forbid"`; no catch-all field or normalization was added.

TDD evidence:

- RED: `test_output_record_boundary_retains_source_from_live_untracked_file_state_capture`
  failed because strict `file_state.untracked` rejected `source` and
  `size_bytes` from a real `classify_file_state()` result.
- GREEN: the same test passed after the explicit schema additions.

## Subsequent producer-contract alignment

The check executor boundary now has an explicit strict contract for
`source_worktree_path`, `execution_worktree_path`,
`execution_snapshot_id`, and `execution_snapshot_ref`; its RED test rejected
all four before the fields were declared. The named FR14/check/driver suite
then passed (16 tests).

The next broad failure separated two canonical file-entry shapes. Live
`PathClassification` records retain `source`, while callback-supplied tracked
and compatibility file-state entries may omit it. `StrictFileEntry.source` is
therefore optional but remains a fixed typed field. Both untracked-present and
tracked-absent strict boundary tests pass, together with the three affected
callback scope tests (20 tests total).

The final producer-contract pass closes the remaining active boundaries without
adding a catch-all field or a strict-model normalizer:

- `StrictArtifactReferenceValue` declares `required`, `section`,
  `max_tokens`, `summarize`, and `summarize_model` with the optionality emitted
  by context-source compilation.
- `StrictDecisionRequestValue.prompt` and
  `StrictVerificationReportValue.candidate_id` are explicit optional fields.
- `StrictFileEntry.hash` and `StrictExternalFileEntry.manifest` cover the
  canonical file-entry shapes. The permissive file-state bridge now retains
  the corresponding concrete `source`, `size_bytes`, `entropy`, and `hash`
  fields while it creates the strict event; it also emits the fixed `port` and
  `schema` discriminator fields instead of relying on omitted defaults.

Focused producer-to-strict boundary tests cover each of those variants. The
field declarations were already present in the inherited uncommitted diff, so
the added tests correctly passed on their first local run; the report does not
misrepresent that as a newly observed RED cycle. The independently reproduced
broad RED failures supplied the file-state and strict checkpoint boundary
regressions; their source repairs preserve strict records through checkpoint
rehydration and accept strict routine snapshots when resolving check bindings.

## Builder verification evidence (2026-07-12)

All commands exited zero:

- Focused Task 5 contracts — `413 passed`.
- Direct producer/checkpoint consequence suite — `245 passed`.
- Fixture corpus — `7 passed`.
- Broad graph matrix — `897 passed`.
- Architecture guard, records codemod `--assert-clean`, and records domain
  inventory — passed at the `44 events / 23 commands` baseline.
- `uv run ruff check .`,
  `uv run pyright src/orchestrator/graph src/orchestrator/graph_runtime`, and
  `git diff --check` — passed; Pyright reported `0 errors`.

## Independent verification evidence (2026-07-12)

All commands exited zero against the final formatted change:

- Targeted post-format suite — `569 passed`.
- Strict/D3 probes — `6 passed`.
- Fixture corpus — `7 passed`.
- Broad graph matrix — `899 passed`.
- Architecture guard, records codemod `--assert-clean`, records inventory,
  Ruff format, Pyright, and `git diff --check` — passed at the
  `44 events / 23 commands` baseline.
- Commit hooks — passed.

Task 5 is complete at commit `d12908002`. D3 retains
`reduce_legacy_event`, `reduce_compact_output_record_accepted`,
`_checkpoint_output_record_payload`, `_parse_output_record_payload`,
`_record_verification_result`, `_verification_payload_outcome`,
`_check_result_payload_status`, and
`_gap_classification_payload_classification`. Per the user's governing
decision, these legacy sites are deleted in Task 13 after database
backup/reset, not Task 9.
