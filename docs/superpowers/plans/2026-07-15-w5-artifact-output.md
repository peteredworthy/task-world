# W5.5 Durable Check Output Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve complete check stdout and stderr in durable content-addressed artifacts while keeping SQLite event payloads bounded and reducers store-free.

**Architecture:** An injected filesystem `ArtifactStore` writes immutable blobs under the main project root before event append. Dispatch replaces over-threshold output with bounded inline tails plus `StoredArtifactRef`; reducers replay only inline metadata, while prompt/API consumers hydrate explicitly. Run-purge mark-and-sweep removes unreferenced blobs after a grace period.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio filesystem I/O, FastAPI, SQLite event store, pytest.

## Global Constraints

- Always use `uv run` for Python commands.
- Artifact storage is rooted at main-project `.orchestrator/artifacts/`, never a run worktree.
- Blob paths are derived only from hashes matching `^sha256:[0-9a-f]{64}$`.
- Stored URIs match `^artifact://sha256/[0-9a-f]{64}$`, never absolute filesystem paths.
- Directory permissions are `0700`; temporary files are flushed and fsynced before atomic rename.
- Blob write precedes event append. Append failure may leave a sweepable orphan; an event never references an unwritten blob.
- `CHECK_OUTPUT_EXTERNALIZE_BYTES = 16_384` UTF-8 bytes.
- `CHECK_OUTPUT_TAIL_CHARS = 4_000` trailing Unicode characters.
- Below threshold, complete output is stored in `*_tail` and no blob is created.
- Above threshold, complete UTF-8 output is stored and `*_tail` contains the final 4,000 characters.
- Reducers, projections, and command handlers never receive `ArtifactStore` and never hydrate artifacts.
- Missing artifacts raise `ArtifactNotFoundError`; hash/size mismatch raises `ArtifactIntegrityError`.
- Garbage collection grace period is `86_400` seconds.
- No S3, git-object storage, reference counting, silent misses, path input, mocks, or global mutable store.

---

### Task 1: Filesystem Artifact Store

**Files:**
- Create: `src/orchestrator/artifacts/models.py`
- Create: `src/orchestrator/artifacts/store.py`
- Create: `src/orchestrator/artifacts/errors.py`
- Create: `src/orchestrator/artifacts/__init__.py`
- Create: `tests/unit/test_artifact_store.py`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: `StoredArtifactRef` from `orchestrator.graph`.
- Produces: `ArtifactStore` protocol and `FilesystemArtifactStore`.

- [ ] **Step 1: Write RED tests**

Test content deduplication, opaque URI construction, mode `0700`, hash/size verification, missing/corrupt errors, and traversal rejection using a real temporary directory.

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/unit/test_artifact_store.py -q`

Expected: import failure for `orchestrator.artifacts`.

- [ ] **Step 3: Implement errors and protocol**

```python
class ArtifactError(Exception):
    pass


class ArtifactNotFoundError(ArtifactError):
    pass


class ArtifactIntegrityError(ArtifactError):
    pass


class ArtifactStore(Protocol):
    async def put(
        self, content: bytes, *, media_type: str, encoding: str | None = None
    ) -> StoredArtifactRef: ...

    async def read(self, ref: StoredArtifactRef) -> bytes: ...

    async def delete(self, ref: StoredArtifactRef) -> None: ...
```

- [ ] **Step 4: Implement filesystem CAS**

Use SHA-256, `artifact_id=content_hash`, hash-derived directories, a same-directory temporary file, `flush`, `os.fsync`, `os.replace`, and directory mode `0700`. Reuse an existing valid blob without rewriting it.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run pytest tests/unit/test_artifact_store.py -q
uv run ruff check src/orchestrator/artifacts tests/unit/test_artifact_store.py
uv run pyright src/orchestrator/artifacts tests/unit/test_artifact_store.py
```

### Task 2: Atomic Check Output Externalization

**Files:**
- Modify: `src/orchestrator/graph/models.py`
- Modify: `src/orchestrator/graph_runtime/dispatch.py`
- Modify: `src/orchestrator/graph_runtime/__init__.py`
- Modify: `tests/unit/test_graph_models.py`
- Modify: `tests/integration/test_graph_runner_e2e.py`
- Create: `tests/integration/test_check_output_artifacts.py`

**Interfaces:**
- Consumes: injected `ArtifactStore`.
- Produces: canonical `CheckResultValue.stdout_tail/stdout_ref/stderr_tail/stderr_ref`.

- [ ] **Step 1: Write RED model and producer tests**

Assert sub-threshold output produces full tails and no refs; over-threshold output writes complete bytes before callback/event append and emits 4,000-character tails plus refs; write failure prevents append; append failure leaves a readable orphan.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/unit/test_graph_models.py -k check_output_artifact \
  tests/integration/test_check_output_artifacts.py -q
```

Expected: missing tail/ref fields and artifact-store injection.

- [ ] **Step 3: Change the canonical model atomically**

```python
class CheckResultValue(StrictNestedModel):
    # Existing semantic fields remain unchanged.
    stdout_tail: str
    stdout_ref: StoredArtifactRef | None = None
    stderr_tail: str
    stderr_ref: StoredArtifactRef | None = None
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool
```

Remove `stdout` and `stderr` in the same commit. `*_truncated` means complete content is not inline; it is true exactly when the corresponding ref exists.

- [ ] **Step 4: Implement deterministic externalization**

```python
CHECK_OUTPUT_EXTERNALIZE_BYTES = 16_384
CHECK_OUTPUT_TAIL_CHARS = 4_000


async def _externalize_check_output(
    output: str, store: ArtifactStore
) -> tuple[str, StoredArtifactRef | None]:
    encoded = output.encode("utf-8")
    if len(encoded) <= CHECK_OUTPUT_EXTERNALIZE_BYTES:
        return output, None
    ref = await store.put(encoded, media_type="text/plain", encoding="utf-8")
    return output[-CHECK_OUTPUT_TAIL_CHARS:], ref
```

Inject the store into dispatch construction. Externalize stdout and stderr before submitting the callback that causes event append.

- [ ] **Step 5: Migrate current readers to tails**

Blocker summaries, activity summaries, projections, and prompts use `stdout_tail` and `stderr_tail`; none hydrate refs.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run pytest tests/unit/test_graph_models.py \
  tests/unit/test_graph_projections.py \
  tests/integration/test_check_output_artifacts.py \
  tests/integration/test_graph_runner_e2e.py -q
git add src/orchestrator/graph/models.py src/orchestrator/graph_runtime \
  tests/unit/test_graph_models.py tests/unit/test_graph_projections.py \
  tests/integration/test_check_output_artifacts.py tests/integration/test_graph_runner_e2e.py
```

### Task 3: Explicit Hydration For Prompts And API

**Files:**
- Modify: `src/orchestrator/graph_runtime/prompts.py`
- Modify: `src/orchestrator/api/deps.py`
- Modify: `src/orchestrator/api/routers/graph.py`
- Modify: `src/orchestrator/api/__init__.py`
- Create: `tests/unit/test_artifact_prompt_hydration.py`
- Create: `tests/integration/test_artifact_api.py`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Produces: bounded prompt hydration and authenticated ranged artifact reads.

- [ ] **Step 1: Write RED tests**

Prompt tests assert tails are default and explicit hydration is bounded. API tests assert `offset >= 0`, `1 <= limit <= 1_048_576`, run authorization, hash/size verification before slicing, and explicit missing/integrity responses.

- [ ] **Step 2: Implement injected hydration service**

Do not read artifact paths directly from prompts or routers. Inject `ArtifactStore`; resolve a typed ref and return a bounded decoded excerpt.

- [ ] **Step 3: Add ranged endpoint**

```text
GET /api/runs/{run_id}/artifacts/{sha256_hex}?offset=0&limit=65536
```

Validate the hash as exactly 64 lowercase hex characters, authorize access through the run, read and verify the full blob, then return the requested byte range.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/unit/test_artifact_prompt_hydration.py \
  tests/integration/test_artifact_api.py -q
uv run ruff check src/orchestrator/graph_runtime/prompts.py src/orchestrator/api tests
uv run pyright src/orchestrator/graph_runtime src/orchestrator/api tests
  tests/unit/test_artifact_prompt_hydration.py tests/integration/test_artifact_api.py \
  docs/ARCHITECTURE.md
```

### Task 4: Mark-And-Sweep Garbage Collection

**Files:**
- Create: `src/orchestrator/artifacts/gc.py`
- Create: `tests/unit/test_artifact_gc.py`
- Modify: `src/orchestrator/workflow/commands/run_lifecycle.py`
- Modify: `src/orchestrator/workflow/service.py`
- Modify: `tests/unit/test_command_handlers.py`
- Modify: `tests/integration/test_workflow_service.py`

**Interfaces:**
- Produces: `collect_artifact_refs(events) -> frozenset[str]` and `sweep_artifacts(now, retained_hashes, grace_seconds=86400)`.

- [ ] **Step 1: Write RED tests**

Use real event models and real temporary files. Assert retained references survive, unmarked files younger than 24 hours survive, older unmarked files are deleted, malformed paths are ignored safely, and repeated sweep is idempotent.

- [ ] **Step 2: Implement typed mark traversal**

Traverse Pydantic models recursively and collect `StoredArtifactRef.content_hash`. Do not branch on event names and do not scan arbitrary JSON keys for strings that resemble hashes.

- [ ] **Step 3: Integrate with run purge**

After `handle_delete_run` appends its tombstone, list graph events for runs not
projected as deleted, mark their refs, and sweep old unmarked blobs. Inject the
collector through `WorkflowService`; do not construct a global store in the
command module. Sweep failure is reported explicitly and does not roll back an
already appended deletion tombstone.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/unit/test_artifact_gc.py -q
uv run ruff check src/orchestrator/artifacts tests/unit/test_artifact_gc.py
uv run pyright src/orchestrator/artifacts tests/unit/test_artifact_gc.py
git add src/orchestrator/artifacts tests/unit/test_artifact_gc.py \
  src/orchestrator/workflow/commands/run_lifecycle.py \
  src/orchestrator/workflow/service.py tests/unit/test_command_handlers.py \
  tests/integration/test_workflow_service.py
git commit -m "Garbage collect unreferenced artifacts"
```

### Task 5: Final Artifact Verification

**Files:**
- Modify: `docs/dynamic-graph/w5-progress-ledger.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Run replay-without-artifacts acceptance**

Create a run with over-threshold stdout/stderr, remove the artifact directory, then run full and compact replay. Expected: projections match and no artifact read occurs.

- [ ] **Step 2: Measure bounded persistence**

Generate 2 MiB stdout and 2 MiB stderr. Assert the SQLite event JSON contains refs and 4,000-character tails and remains below 32 KiB excluding other metadata.

- [ ] **Step 3: Run final gates**

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright
git diff --check
```

- [ ] **Step 4: Record evidence and commit**

Record exact test counts, database row size, blob sizes/hashes, replay-without-artifacts result, and GC evidence.

```bash
git add docs/dynamic-graph/w5-progress-ledger.md docs/ARCHITECTURE.md
git commit -m "Verify durable check output artifacts"
```
