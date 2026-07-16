# W5.5 Durable Check Output Artifacts Design

## Objective

Recover complete check output that is currently discarded while keeping large
stdout, stderr, and diagnostic bodies out of SQLite graph event payloads. The
event store remains event-agnostic: producers externalize large content before
append, and canonical events contain bounded inline tails plus durable typed
references.

This work follows W5 typed-payload completion. W5 defines the reference type but
does not change `CheckResultValue.stdout` or `CheckResultValue.stderr`; the
record-shape and producer cutover happen atomically in W5.5 when the artifact
store exists.

## Current Problem

`graph_runtime/dispatch.py` currently trims check stdout and stderr to the last
20,000 characters before constructing a check result. Full output is therefore
lost before event persistence. The retained tails are then stored inline in
SQLite and can be loaded by compact projection reads that retain the complete
record `value`.

The design must solve both data loss and database bloat without teaching SQL
about event families and without silently dropping fields at the storage
boundary.

## Reference Model

W5 introduces this strict nested model for later use:

```python
class StoredArtifactRef(StrictNestedModel):
    artifact_id: str
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(ge=0)
    media_type: str
    encoding: str | None = None
    storage_uri: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
```

`StoredArtifactRef` is a durable content identity. It does not include prompt
hydration policy, token limits, summarization configuration, sections, or a
preview. `ArtifactReferenceValue` remains the prompt-context pointer model and
is not reused as durable blob identity. A later change may embed a
`StoredArtifactRef` inside it.

## Storage Backend

Use a content-addressed filesystem rooted at the main project checkout:

```text
.orchestrator/artifacts/sha256/<first-two-hex>/<remaining-hex>
```

The path is never inside a run worktree and never stored directly in an event.
Events carry only `artifact://sha256/<hex>`. The store validates the hash and
derives the filesystem path itself. `.orchestrator/` remains gitignored, and
the artifact directory is created with mode `0700`.

Define a small injected interface:

```python
class ArtifactStore(Protocol):
    async def put(self, content: bytes, media_type: str, encoding: str | None) -> StoredArtifactRef: ...
    async def read(self, ref: StoredArtifactRef) -> bytes: ...
    async def delete(self, ref: StoredArtifactRef) -> None: ...
```

The filesystem implementation writes a temporary file, flushes and fsyncs it,
then atomically renames it to the hash-derived path. Existing hash paths are
reused. Hashes use the existing `sha256:<hex>` format from file-state code.

## Producer Cutover

Externalization occurs in `graph_runtime/dispatch.py`, where complete subprocess
bytes already exist in the orchestrator process. Reducers and graph-kernel
commands never receive an artifact store.

W5.5 replaces inline full-output fields atomically with:

```python
stdout_tail: str
stdout_ref: StoredArtifactRef | None = None
stderr_tail: str
stderr_ref: StoredArtifactRef | None = None
```

The exact externalization threshold and tail bound are constants established by
the W5.5 implementation plan after representative output-size measurements.
The deterministic policy is:

- Below the UTF-8 byte threshold: keep the complete value in `*_tail`; no blob
  and no reference.
- Above the threshold: write complete UTF-8 bytes to the artifact store and
  keep a bounded trailing excerpt in `*_tail`.

Blob write always precedes event append. A failed append may leave an orphaned
content-addressed blob; garbage collection removes it after the grace period.
An event must never reference content that was not durably written.

## Replay And Hydration

Reducers use tails, hashes, sizes, and other inline semantic metadata. They do
not hydrate artifacts and do not accept an artifact-store dependency. Full and
compact replay must succeed with the artifact directory absent.

Hydration is an explicit injected service for:

- prompt construction that requests bounded excerpts; and
- an authenticated API range endpoint using `offset` and `limit`.

Reads verify full content size and SHA-256 before returning a requested range.
Missing content raises `ArtifactNotFoundError`; size or hash mismatch raises
`ArtifactIntegrityError`. Neither case silently returns an empty value.

## Garbage Collection

Use mark-and-sweep rather than reference counts. On run purge:

1. Walk typed events for retained runs and collect every `StoredArtifactRef`.
2. Walk content-addressed artifact files.
3. Delete unmarked files older than a 24-hour grace period.

Typed model traversal discovers reference fields; SQL remains unaware of event
types. The grace period covers write-before-append crashes.

## Security

- Validate hashes with `^sha256:[0-9a-f]{64}$`.
- Derive paths only from validated hashes, never from URI/path input.
- Verify hash and size on every read.
- Use main-root private storage with mode `0700`.
- Provide delete-by-hash for compromised secret output.
- Hydration authorization follows run access; possession of a hash is not
  authorization.

## W5 Boundary

W5 Task 5 may:

- add and export `StoredArtifactRef`;
- add strict model tests for reference identity; and
- generate the four compact-read retention sets from typed event
  specifications.

W5 Task 5 must not:

- rename or remove current check-output fields;
- silently strip event payload values;
- add filesystem artifact writes, hydration, API endpoints, or GC; or
- claim that global generated retention tuples solve complete-value read
  amplification.

The current complete-`value` read and 20,000-character truncation remain an
explicit temporary limitation until W5.5 lands.

## Acceptance

W5.5 is complete only when:

- sub-threshold output creates no blob;
- over-threshold complete stdout/stderr round-trip through references;
- SQLite event JSON contains bounded tails and references, not full large
  bodies;
- replay succeeds and matches compact replay with the artifact directory
  deleted;
- prompt and API hydration verify content and return bounded ranges;
- missing and corrupted artifacts raise explicit domain errors;
- worktree deletion does not invalidate references;
- event-append failure leaves only a sweepable orphan;
- mark-and-sweep preserves retained references and removes expired orphans; and
- multi-megabyte check output does not produce multi-megabyte event rows.
