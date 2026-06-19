# Feature spec — Versioned File Workspace for the desktop file manager

This spec is **identical input for every orchestration arm** (graph / idea-to-plan /
mind-the-gap). It is the only requirements document the arms receive. Implement it in the
existing FastAPI app (`main.py`, storage rooted at `desktop_fs/`). You may add modules, a
metadata store, and tests, but the existing endpoints below must keep working.

The hard part is the **interactions** between capabilities (§7). A correct implementation of
each capability in isolation is not enough — versioning, trash, tags and quota must compose.

## Existing app (do not break)

`GET /api/files`, `GET /api/files/read`, `POST /api/files/write`, `POST /api/files/mkdir`,
`DELETE /api/files`, `POST /api/files/rename`, `GET /`. `safe_path()` blocks path escapes
(keep this guarantee on every new endpoint → 403 on escape).

Metadata you introduce (versions, trash, tags, quota, activity) must live **outside** the
visible tree — use `desktop_fs/.meta/` — and must **never** appear in `GET /api/files`
listings or in search results. Metadata persists across process restart. Timestamps are
ISO-8601 UTC strings.

## 1 — Version history

Every successful `POST /api/files/write` to a path that **already exists as a file** must
first snapshot the prior content as an immutable, per-path, 1-indexed version before
overwriting. New-file writes produce no version.

- `GET /api/files/versions?path=<p>` → `{"path", "versions": [{"version", "size",
  "created_at", "hash": "sha256:<hex>"}, ...]}` newest-last. 404 if the file never existed.
- `GET /api/files/versions/read?path&version` → `{"path", "version", "content"}`. 404 unknown.
- `POST /api/files/versions/restore` `{"path", "version"}` → restores that version as current
  (which itself snapshots the pre-restore content). Returns `{"path", "restored_version",
  "current_version"}`.
- `GET /api/files/versions/diff?path&from&to` → `{"path", "from", "to", "diff"}` unified text
  diff; `to` may be the literal `current`. 404 if a version is missing; 400
  `{"detail": "binary content"}` for binary.
- Retention: keep at most **20** newest versions per path; version numbers are monotonic and
  never reused.

## 2 — Trash bin

`DELETE /api/files` moves files **and** directories to trash instead of hard-deleting.

- `GET /api/trash` → `{"items": [{"trash_id", "original_path", "name", "is_dir", "size",
  "deleted_at"}, ...]}` newest-first.
- `POST /api/trash/restore` `{"trash_id"}` → restore to original path; on collision restore to
  `name (restored)`, then ` (restored 2)`… returning the actual `restored_to`; recreate
  missing parents; 404 unknown id.
- `DELETE /api/trash?trash_id` → purge one (404 unknown). `DELETE /api/trash/all` → empty,
  returns `{"purged": int}`.
- Two deletes of the same path are independently restorable (distinct `trash_id`s).

## 3 — Search

`GET /api/search` params: `name` (substring, case-insensitive, on name), `content`
(substring, case-insensitive, file text only), `path_prefix`, `type` (`file`|`dir`),
`min_size`, `max_size`, `tag` (exact tag match, repeatable — match files having **all**
given tags). Returns `{"query": {...echoed...}, "results": [{"path", "name", "is_dir",
"size", "match": "name"|"content"|"both"|"tag"|"filter", "tags": [...]}, ...]}` sorted by
path, recursive from root or `path_prefix`. Content matching skips binary/undecodable files.
`.meta/` and trashed items are never returned.

## 4 — Move & Copy

- `POST /api/files/move` `{"path", "dest"}` → move a file/dir to `dest` (a full path). Moving
  a file **carries its version history and tags** to the new path. 404 missing source; 409 if
  dest exists; recreate missing parent dirs.
- `POST /api/files/copy` `{"path", "dest"}` → copy a file/dir to `dest`. A copy **duplicates
  the current content and tags but starts with empty version history**. 404/409 as above.

## 5 — Tagging

- `POST /api/files/tags` `{"path", "tags": [...]}` → set (replace) the tag list on a file/dir.
- `GET /api/files/tags?path` → `{"path", "tags": [...]}` (sorted, unique). 404 if path missing.
- Tags persist and **follow rename and move**; `copy` duplicates them; purging from trash
  drops them. Tags never appear in `GET /api/files` listings.

## 6 — Quota

A configurable cap on **live** file bytes (sum of current file sizes, excluding `.meta/`,
versions, and trashed content). Default cap **1,000,000** bytes; settable via
`POST /api/quota` `{"max_bytes": int}`; readable via `GET /api/quota` →
`{"max_bytes", "used_bytes", "available_bytes"}`.

- A `write`/`copy`/`restore`(trash or version) that would push live usage over the cap returns
  **413** `{"detail": "quota exceeded"}` and makes **no change** (no partial write, no version
  snapshot, no trash mutation).
- Trashed bytes and version bytes do **not** count toward the live cap.

## 7 — Interactions (the part that must compose)

- **Trash carries history + tags.** Deleting a file moves it to trash *together with* its
  version history and tags. Restoring brings content, full version history, and tags back.
  Purging a trash entry permanently drops its versions and tags too.
- **Move carries history + tags** (per §4); **copy duplicates content + tags, not history**.
- **Rename carries history + tags** (the existing rename endpoint must now preserve them).
- **Restore respects quota** (§6): a trash/version restore that would exceed the live cap
  returns 413 and changes nothing.
- **Search reflects tags** (§3 `tag` param and `tags` field) and still excludes `.meta/`/trash.
- **Versioning + retention** still applies to files that arrived via move/restore.

## 8 — Activity log

`GET /api/activity?limit=<n>` → `{"events": [{"action", "path", "at"}, ...]}` newest-first,
where `action` ∈ {`write`,`delete`,`restore`,`rename`,`move`,`copy`,`version_restore`,
`tag`,`purge`}. Keep at least the most recent 100 events (a bounded ring is fine). The log is
metadata (never listed/searched).

## Definition of done

All eight sections implemented and persistent; existing endpoints intact; interactions in §7
compose correctly; the app starts (`uvicorn main:app`) with no import errors; your own tests
pass. The graders run a separate, independent acceptance suite you will not see.
