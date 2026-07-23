# Migrate Claude SDK History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert mutable historical `claude_sdk` database values to `retired` and safely deserialize immutable historical state and event payloads.

**Architecture:** Add one linear Alembic data migration from `zf1g2h3i4j5k` that updates the five relational columns while retaining a deterministic winner for each `(runner_type, profile)` uniqueness conflict. At repository, state-file, and workflow-event read boundaries, apply the Task 12 shared normalizer to in-memory copies only; persistent event and journal bytes are never rewritten.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, Pydantic v2, pytest/pytest-asyncio, SQLite temporary databases.

## Global Constraints

- Migration revision is `zg1h2i3j4k5l` with `down_revision = "zf1g2h3i4j5k"` and is the sole Alembic head.
- Update only `runs.runner_type`, `attempts.runner_type`, `cost_records.agent_runner_type`, `interaction_log_artifacts.agent_runner_type`, and `agent_runner_model_profile_defaults.runner_type`.
- Resolve model-default uniqueness conflicts deterministically before changing that table's `runner_type` values.
- Never run Alembic upgrade against the project `orchestrator.db`; tests use temporary or in-memory databases.
- Do not mutate `events_v2.payload` or state/journal file bytes during read-time normalization.
- Normalize only values at the keys `runner_type`, `agent_runner_type`, `old_agent`, and `new_agent` in event JSON.

---

### Task 1: Write migration and read-boundary RED tests

**Files:**
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_session_persistence.py`
- Modify: `tests/integration/test_projection_recovery.py`
- Modify: `tests/unit/test_pydantic_events.py`

**Interfaces:**
- Consumes: raw `claude_sdk` values written directly to pre-migration schema and historical JSON payloads.
- Produces: failing coverage for relational conversion, collision selection, immutable bytes, state snapshots, and event payload normalization.

- [ ] **Step 1: Write a pre-migration database test**

Create a temporary SQLite database, downgrade it to `zf1g2h3i4j5k`, hand-insert a `claude_sdk` value in every required relational table, including colliding model-default rows for one profile, and record IDs/content plus raw `events_v2.payload` bytes.

- [ ] **Step 2: Assert the migration target**

Upgrade the temporary database to `zg1h2i3j4k5l`; assert all five relational locations now contain `retired`, the deterministic model-default survivor is retained, unrelated IDs/content remain unchanged, and the stored event payload bytes equal their pre-upgrade values.

- [ ] **Step 3: Write immutable state and event tests**

Hand-write a session JSON snapshot containing `claude_sdk` at a run and nested attempt, call `SessionStateManager.load()`, assert both deserialize as `AgentRunnerType.RETIRED`, and assert `read_bytes()` remains exactly unchanged. Hand-write historical event JSON containing nested runner-key values and a non-runner occurrence of the same string; assert `deserialize_event` normalizes only the key-scoped values and leaves the source payload string unchanged.

- [ ] **Step 4: Run the focused RED suite**

Run: `uv run pytest tests/integration/test_migrations.py tests/integration/test_session_persistence.py tests/integration/test_projection_recovery.py tests/unit/test_pydantic_events.py -q`

Expected: failure because the migration revision and required normalizations do not yet exist.

### Task 2: Implement the linear migration and normalization boundaries

**Files:**
- Create: `src/orchestrator/db/migrations/versions/zg1h2i3j4k5l_retire_claude_sdk_runner.py`
- Modify: `src/orchestrator/db/access/repositories.py`
- Modify: `src/orchestrator/state/session.py`
- Modify: `src/orchestrator/workflow/events/__init__.py`

**Interfaces:**
- Consumes: `normalize_persisted_agent_runner_type(value)` from `orchestrator.config`.
- Produces: `retired` relational data and in-memory `AgentRunnerType.RETIRED` event/state/domain values.

- [ ] **Step 1: Add the Alembic migration**

Create revision `zg1h2i3j4k5l` with parent `zf1g2h3i4j5k`. Delete the deterministic `claude_sdk` duplicate for each profile where an existing `retired` default would conflict, then update the five named columns. Include a docstring explaining that downgrade cannot restore whether a `retired` value originated as `claude_sdk`.

- [ ] **Step 2: Normalize repository values**

Import `normalize_persisted_agent_runner_type` from `orchestrator.config`; have `_agent_runner_type` call it before retaining existing `script` and `user_managed` legacy behavior and unknown-value warning behavior.

- [ ] **Step 3: Normalize copied session JSON**

Deep-copy parsed session data in `SessionStateManager.load`, map the run-level `agent_runner_type` and each nested attempt's `agent_runner_type` through the shared normalizer-compatible value representation, then Pydantic-validate the copy without writing to the persistence path.

- [ ] **Step 4: Normalize event JSON by key**

Parse the incoming payload, recursively traverse dict/list contents, map only string `claude_sdk` values below `runner_type`, `agent_runner_type`, `old_agent`, or `new_agent` keys to `retired`, and pass the transformed in-memory object to Pydantic. Do not serialize or persist the original payload.

- [ ] **Step 5: Run the focused GREEN suite and migration head check**

Run: `uv run pytest tests/integration/test_migrations.py tests/integration/test_session_persistence.py tests/integration/test_projection_recovery.py tests/unit/test_pydantic_events.py -q && uv run alembic -c alembic.ini heads`

Expected: focused tests pass and exactly one head, `zg1h2i3j4k5l`, prints.

### Task 3: Verify and commit

**Files:**
- Modify: `.superpowers/sdd/task-13-report.md`

**Interfaces:**
- Consumes: focused and whole-suite results plus self-review evidence.
- Produces: one non-amended implementation commit and requested report.

- [ ] **Step 1: Run static and full tests once**

Run `uv run ruff check .`, `uv run pyright`, and `uv run pytest -q` once each after focused checks pass.

- [ ] **Step 2: Self-review the diff**

Inspect `git diff --check`, the staged diff, migration parent/head output, and the tests' immutable-byte assertions; correct any scope or correctness issue found.

- [ ] **Step 3: Commit and report**

Commit only Task 13 source/tests with `feat: migrate Claude SDK history to retired runner` without amend. Write `.superpowers/sdd/task-13-report.md` with status, commit, test commands/results, immutable-data guarantees, and any concerns.
