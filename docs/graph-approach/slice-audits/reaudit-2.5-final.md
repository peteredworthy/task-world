# Slice 2.5 — Final crash-safety re-audit

Date: 2026-06-13. Auditor: independent review (the fixer2 crash-safety changes
were never re-audited after the original BOUNCE; this closes that gap).

Ground truth: PRD §20.2 (boundary check / cleanup must be represented by
`cleanup_requested` + `cleanup_applied`, hidden cleanup forbidden) and §20.3
(secret-like files never captured into snapshot storage).

## Original BOUNCE concern (reaudit-2.5.log)

> retroactive-secret cleanup is not crash-safe: the system can durably know a
> snapshot is compromised while leaving the old ref restorable or lacking a
> clean superseding record after restart.

## Findings — all CLOSED

| Concern | Evidence | Status |
|---|---|---|
| Cleanup survives a crash before the filesystem side effect | `cleanup_requested` → durable `snapshot_cleanup` outbox row (`outbox.py:68-75`); `recover()` redispatches pending cleanups (`recovery.py`); idempotent `_dispatch_snapshot_cleanup` checks `_cleanup_applied_exists` first (`dispatch.py`). Test `test_snapshot_cleanup_recovers_when_dispatch_fails_before_side_effect`. | CLOSED |
| Crash after ref delete but before recording | Idempotent redispatch completes; test `test_snapshot_cleanup_recovers_after_ref_delete_before_record`. | CLOSED |
| Old compromised ref restorable | `apply_cleanup_requested` calls `delete_snapshot_ref` (`graph_runtime/file_state.py`); tests assert real git state via `git show-ref`: `_ref_exists(old_ref) is False`, `_ref_exists(new_ref) is True` after cleanup AND after crash+recovery (`test_graph_outbox_crash_points.py:587,620-621,659-683`). | CLOSED |
| Compromised snapshot bindable during the crash window | Projection marks `compromised=True` AND `superseded_pending=True` on `cleanup_requested` (`projections.py:809-810`); runtime binding guard refuses to bind such a record (`dispatch.py:_guard_no_pending_compromised_file_state_bindings`, raises `CompromisedFileStateError`). Test `test_compromised_file_state_binding_is_refused_before_cleanup_completes`. | CLOSED |
| Forged/invalid superseding record | `_apply_record_cleanup_applied` (`commands.py:1299-1424`) has 12 rejection paths: missing/unknown cleanup_id, duplicate, record mismatch, snapshot mismatch, missing superseding record, supersedes-target mismatch, same-snapshot supersede, retained secret path, invalid model. Unit tests `test_record_cleanup_applied_rejects_*` (4). | CLOSED |

## Adversarial pass

- Same-snapshot supersede → rejected (`test_record_cleanup_applied_rejects_same_snapshot_supersede`).
- Superseding record retaining a secret path → rejected
  (`test_record_cleanup_applied_rejects_superseding_record_with_secret_path`).
- Duplicate cleanup replay → rejected + dispatch no-op idempotent
  (`test_record_cleanup_applied_rejects_duplicate_cleanup`).

## Fresh run

`uv run pytest tests/unit/test_graph_gatekeeper.py
tests/integration/test_graph_gatekeeper_flow.py
tests/integration/test_graph_outbox_crash_points.py
tests/integration/test_graph_file_state_boundary.py -q` → 36 passed in ~5s.

## Verdict

**ACCEPT.** No gaps. The fixer2 crash-safety work is real, the original BOUNCE
concerns are each closed by named crash-point tests with real git-state
assertions (not log-and-hope), and §20.2/§20.3 are honoured. Slice 2.5 is done.
