"""Independent acceptance oracle for the Versioning/Trash/Search feature.

Each test is a single objective check against the spec contracts. Pass count is
the effectiveness/correctness score for an arm. The arms never see this file.
"""

from __future__ import annotations


# ---------------------------------------------------------------- baseline (regression)
def test_existing_list_still_works(client):
    r = client.get("/api/files")
    assert r.status_code == 200
    names = {e["name"] for e in r.json()}
    assert {"readme.txt", "Documents", "Pictures"} <= names


def test_meta_store_hidden_from_listing(client):
    # force metadata creation, then ensure .meta is not listed
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    r = client.get("/api/files")
    names = {e["name"] for e in r.json()}
    assert ".meta" not in names


# ------------------------------------------------------------------------ versioning
def test_overwrite_creates_one_version(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "second\n"})
    r = client.get("/api/files/versions", params={"path": "readme.txt"})
    assert r.status_code == 200
    vs = r.json()["versions"]
    assert len(vs) == 1
    assert vs[0]["version"] == 1
    assert vs[0]["hash"].startswith("sha256:")


def test_new_file_has_no_version(client):
    client.post("/api/files/write", json={"path": "brand_new.txt", "content": "x\n"})
    r = client.get("/api/files/versions", params={"path": "brand_new.txt"})
    assert r.status_code == 200
    assert r.json()["versions"] == []


def test_versions_accumulate_ordered(client):
    for n in range(2, 5):
        client.post("/api/files/write", json={"path": "readme.txt", "content": f"v{n}\n"})
    vs = client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"]
    nums = [v["version"] for v in vs]
    assert nums == sorted(nums)
    assert len(vs) == 3  # 3 overwrites of original


def test_version_read_returns_prior_content(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "changed\n"})
    r = client.get("/api/files/versions/read", params={"path": "readme.txt", "version": 1})
    assert r.status_code == 200
    assert r.json()["content"] == "root readme contents\n"


def test_version_read_missing_is_404(client):
    r = client.get("/api/files/versions/read", params={"path": "readme.txt", "version": 99})
    assert r.status_code == 404


def test_restore_brings_back_old_content(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "newA\n"})
    client.post("/api/files/write", json={"path": "readme.txt", "content": "newB\n"})
    r = client.post("/api/files/versions/restore", json={"path": "readme.txt", "version": 1})
    assert r.status_code == 200
    cur = client.get("/api/files/read", params={"path": "readme.txt"}).json()["content"]
    assert cur == "root readme contents\n"


def test_restore_snapshots_pre_restore_content(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "preR\n"})
    client.post("/api/files/versions/restore", json={"path": "readme.txt", "version": 1})
    vs = client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"]
    # original snapshot (v1) plus the pre-restore "preR" snapshot
    assert len(vs) >= 2
    contents = [
        client.get(
            "/api/files/versions/read", params={"path": "readme.txt", "version": v["version"]}
        ).json()["content"]
        for v in vs
    ]
    assert "preR\n" in contents


def test_diff_between_versions(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "line one\n"})
    r = client.get(
        "/api/files/versions/diff", params={"path": "readme.txt", "from": 1, "to": "current"}
    )
    assert r.status_code == 200
    diff = r.json()["diff"]
    assert "root readme contents" in diff and "line one" in diff


def test_diff_missing_version_404(client):
    r = client.get(
        "/api/files/versions/diff", params={"path": "readme.txt", "from": 1, "to": 50}
    )
    assert r.status_code == 404


def test_retention_caps_at_20(client):
    for n in range(30):
        client.post("/api/files/write", json={"path": "readme.txt", "content": f"r{n}\n"})
    vs = client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"]
    assert len(vs) <= 20
    nums = [v["version"] for v in vs]
    assert nums == sorted(nums)
    assert max(nums) >= 25  # numbers monotonic, not reused


# ----------------------------------------------------------------------------- trash
def test_delete_moves_to_trash(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    listing = {e["name"] for e in client.get("/api/files").json()}
    assert "readme.txt" not in listing
    items = client.get("/api/trash").json()["items"]
    assert any(i["original_path"].endswith("readme.txt") for i in items)


def test_trash_item_shape(client):
    client.delete("/api/files", params={"path": "Documents/notes.txt"})
    item = client.get("/api/trash").json()["items"][0]
    assert {"trash_id", "original_path", "name", "is_dir", "size", "deleted_at"} <= set(item)
    assert item["name"] == "notes.txt"
    assert item["is_dir"] is False


def test_trash_restore(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    r = client.post("/api/trash/restore", json={"trash_id": tid})
    assert r.status_code == 200
    assert client.get("/api/files/read", params={"path": "readme.txt"}).status_code == 200


def test_trash_restore_collision_renames(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    # recreate a file at the original path
    client.post("/api/files/write", json={"path": "readme.txt", "content": "occupied\n"})
    r = client.post("/api/trash/restore", json={"trash_id": tid})
    assert r.status_code == 200
    restored_to = r.json()["restored_to"]
    assert restored_to != "readme.txt"
    assert client.get("/api/files/read", params={"path": restored_to}).status_code == 200
    # original untouched
    assert client.get("/api/files/read", params={"path": "readme.txt"}).json()["content"] == "occupied\n"


def test_trash_delete_directory_restorable(client):
    client.post("/api/files/write", json={"path": "Documents/sub/deep.txt", "content": "deep\n"})
    client.delete("/api/files", params={"path": "Documents/sub"})
    item = next(i for i in client.get("/api/trash").json()["items"] if i["name"] == "sub")
    assert item["is_dir"] is True
    client.post("/api/trash/restore", json={"trash_id": item["trash_id"]})
    assert client.get("/api/files/read", params={"path": "Documents/sub/deep.txt"}).status_code == 200


def test_purge_one(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    r = client.delete("/api/trash", params={"trash_id": tid})
    assert r.status_code == 200
    assert client.get("/api/trash").json()["items"] == []


def test_purge_unknown_404(client):
    assert client.delete("/api/trash", params={"trash_id": "nope"}).status_code == 404


def test_empty_all_trash(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    client.delete("/api/files", params={"path": "Documents/notes.txt"})
    r = client.delete("/api/trash/all")
    assert r.status_code == 200
    assert r.json()["purged"] >= 2
    assert client.get("/api/trash").json()["items"] == []


def test_two_deletes_same_path_both_restorable(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    client.post("/api/files/write", json={"path": "readme.txt", "content": "again\n"})
    client.delete("/api/files", params={"path": "readme.txt"})
    items = client.get("/api/trash").json()["items"]
    same = [i for i in items if i["original_path"].endswith("readme.txt")]
    assert len(same) == 2
    assert len({i["trash_id"] for i in same}) == 2


# ---------------------------------------------------------------------------- search
def test_search_by_name(client):
    r = client.get("/api/search", params={"name": "notes"})
    assert r.status_code == 200
    paths = {x["path"] for x in r.json()["results"]}
    assert any(p.endswith("Documents/notes.txt") for p in paths)


def test_search_by_content(client):
    r = client.get("/api/search", params={"content": "gamma"})
    results = r.json()["results"]
    assert any(x["path"].endswith("Documents/notes.txt") for x in results)
    assert all(x["match"] in ("content", "both") for x in results)


def test_search_type_dir(client):
    r = client.get("/api/search", params={"type": "dir"})
    assert all(x["is_dir"] for x in r.json()["results"])
    assert any(x["name"] == "Documents" for x in r.json()["results"])


def test_search_path_prefix(client):
    client.post("/api/files/write", json={"path": "Documents/inside.txt", "content": "zzz\n"})
    r = client.get("/api/search", params={"path_prefix": "Documents", "name": ".txt"})
    paths = {x["path"] for x in r.json()["results"]}
    assert paths
    assert all("Documents" in p for p in paths)


def test_search_size_filter(client):
    client.post("/api/files/write", json={"path": "big.txt", "content": "x" * 500})
    r = client.get("/api/search", params={"min_size": 400})
    names = {x["name"] for x in r.json()["results"]}
    assert "big.txt" in names
    assert "readme.txt" not in names


def test_search_excludes_meta_and_trash(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "make meta\n"})
    client.delete("/api/files", params={"path": "Documents/welcome.txt"})
    r = client.get("/api/search", params={})
    paths = {x["path"] for x in r.json()["results"]}
    assert not any(".meta" in p for p in paths)
    assert not any(p.endswith("welcome.txt") for p in paths)


def test_search_sorted_by_path(client):
    r = client.get("/api/search", params={"type": "file"})
    paths = [x["path"] for x in r.json()["results"]]
    assert paths == sorted(paths)


# ------------------------------------------------------------------------ cross-cutting
def test_path_escape_blocked_versions(client):
    r = client.get("/api/files/versions", params={"path": "../../etc/passwd"})
    assert r.status_code == 403


def test_metadata_persists_across_reload(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "persisted\n"})
    # new TestClient on the same on-disk store (simulating restart) via fresh import
    import importlib

    import main

    main2 = importlib.reload(main)
    from fastapi.testclient import TestClient

    with TestClient(main2.app) as c2:
        vs = c2.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"]
        assert len(vs) >= 1


# =========================================================== move & copy (cap 4)
def test_move_relocates_file(client):
    r = client.post("/api/files/move", json={"path": "readme.txt", "dest": "Documents/moved.txt"})
    assert r.status_code == 200
    assert client.get("/api/files/read", params={"path": "readme.txt"}).status_code == 404
    assert client.get("/api/files/read", params={"path": "Documents/moved.txt"}).json()["content"] == "root readme contents\n"


def test_move_carries_version_history(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    client.post("/api/files/move", json={"path": "readme.txt", "dest": "moved.txt"})
    vs = client.get("/api/files/versions", params={"path": "moved.txt"}).json()["versions"]
    assert len(vs) >= 1
    assert client.get("/api/files/versions", params={"path": "readme.txt"}).status_code == 404


def test_move_missing_404(client):
    assert client.post("/api/files/move", json={"path": "nope.txt", "dest": "x.txt"}).status_code == 404


def test_move_dest_exists_409(client):
    assert client.post("/api/files/move", json={"path": "readme.txt", "dest": "Documents/notes.txt"}).status_code == 409


def test_copy_duplicates_content(client):
    r = client.post("/api/files/copy", json={"path": "readme.txt", "dest": "copy.txt"})
    assert r.status_code == 200
    assert client.get("/api/files/read", params={"path": "readme.txt"}).status_code == 200
    assert client.get("/api/files/read", params={"path": "copy.txt"}).json()["content"] == "root readme contents\n"


def test_copy_has_no_version_history(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    client.post("/api/files/copy", json={"path": "readme.txt", "dest": "copy.txt"})
    assert client.get("/api/files/versions", params={"path": "copy.txt"}).json()["versions"] == []


# =============================================================== tagging (cap 5)
def test_set_and_get_tags(client):
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["red", "doc", "red"]})
    tags = client.get("/api/files/tags", params={"path": "readme.txt"}).json()["tags"]
    assert tags == ["doc", "red"]


def test_get_tags_missing_404(client):
    assert client.get("/api/files/tags", params={"path": "ghost.txt"}).status_code == 404


def test_tags_follow_rename(client):
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["keepme"]})
    client.post("/api/files/rename", json={"path": "readme.txt", "new_name": "renamed.txt"})
    assert client.get("/api/files/tags", params={"path": "renamed.txt"}).json()["tags"] == ["keepme"]


def test_copy_carries_tags(client):
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["t1"]})
    client.post("/api/files/copy", json={"path": "readme.txt", "dest": "copy.txt"})
    assert client.get("/api/files/tags", params={"path": "copy.txt"}).json()["tags"] == ["t1"]


def test_search_by_tag(client):
    client.post("/api/files/tags", json={"path": "Documents/notes.txt", "tags": ["important"]})
    r = client.get("/api/search", params={"tag": "important"})
    paths = {x["path"] for x in r.json()["results"]}
    assert any(p.endswith("Documents/notes.txt") for p in paths)


def test_search_by_multiple_tags_is_and(client):
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["a", "b"]})
    client.post("/api/files/tags", json={"path": "Documents/notes.txt", "tags": ["a"]})
    r = client.get("/api/search", params=[("tag", "a"), ("tag", "b")])
    paths = {x["path"] for x in r.json()["results"]}
    assert any(p.endswith("readme.txt") for p in paths)
    assert not any(p.endswith("notes.txt") for p in paths)


# ================================================================ quota (cap 6)
def test_quota_default(client):
    q = client.get("/api/quota").json()
    assert q["max_bytes"] == 1000000
    assert q["used_bytes"] >= 0
    assert q["available_bytes"] == q["max_bytes"] - q["used_bytes"]


def test_quota_set(client):
    client.post("/api/quota", json={"max_bytes": 500})
    assert client.get("/api/quota").json()["max_bytes"] == 500


def test_quota_blocks_oversize_write_413(client):
    used = client.get("/api/quota").json()["used_bytes"]
    client.post("/api/quota", json={"max_bytes": used + 50})
    r = client.post("/api/files/write", json={"path": "big.txt", "content": "x" * 200})
    assert r.status_code == 413
    assert client.get("/api/files/read", params={"path": "big.txt"}).status_code == 404


def test_quota_no_partial_on_overwrite(client):
    used = client.get("/api/quota").json()["used_bytes"]
    client.post("/api/quota", json={"max_bytes": used + 5})
    r = client.post("/api/files/write", json={"path": "readme.txt", "content": "y" * 300})
    assert r.status_code == 413
    # original content and version count unchanged
    assert client.get("/api/files/read", params={"path": "readme.txt"}).json()["content"] == "root readme contents\n"
    assert client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"] == []


def test_versions_dont_count_to_quota(client):
    base = client.get("/api/quota").json()["used_bytes"]
    for n in range(5):
        client.post("/api/files/write", json={"path": "readme.txt", "content": "12345\n"})
    used = client.get("/api/quota").json()["used_bytes"]
    # used reflects only the single current file, not the 5 stored versions
    assert used < base + 200


def test_trash_doesnt_count_to_quota(client):
    before = client.get("/api/quota").json()["used_bytes"]
    client.delete("/api/files", params={"path": "Documents/notes.txt"})
    after = client.get("/api/quota").json()["used_bytes"]
    assert after < before


# ===================================================== interactions (cap 7) =========
def test_trash_restore_keeps_version_history(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    client.post("/api/trash/restore", json={"trash_id": tid})
    vs = client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"]
    assert len(vs) >= 1


def test_trash_restore_keeps_tags(client):
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["surv"]})
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    client.post("/api/trash/restore", json={"trash_id": tid})
    assert client.get("/api/files/tags", params={"path": "readme.txt"}).json()["tags"] == ["surv"]


def test_purge_drops_versions_and_tags(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    client.post("/api/files/tags", json={"path": "readme.txt", "tags": ["gone"]})
    client.delete("/api/files", params={"path": "readme.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    client.delete("/api/trash", params={"trash_id": tid})
    # recreate at same path: must be a clean slate
    client.post("/api/files/write", json={"path": "readme.txt", "content": "fresh\n"})
    assert client.get("/api/files/versions", params={"path": "readme.txt"}).json()["versions"] == []
    assert client.get("/api/files/tags", params={"path": "readme.txt"}).json()["tags"] == []


def test_rename_carries_version_history(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    client.post("/api/files/rename", json={"path": "readme.txt", "new_name": "renamed.txt"})
    vs = client.get("/api/files/versions", params={"path": "renamed.txt"}).json()["versions"]
    assert len(vs) >= 1


def test_restore_respects_quota_413(client):
    client.delete("/api/files", params={"path": "Documents/notes.txt"})
    tid = client.get("/api/trash").json()["items"][0]["trash_id"]
    used = client.get("/api/quota").json()["used_bytes"]
    client.post("/api/quota", json={"max_bytes": used + 1})  # no room for the 16-byte file
    r = client.post("/api/trash/restore", json={"trash_id": tid})
    assert r.status_code == 413
    # trash entry untouched
    assert any(i["trash_id"] == tid for i in client.get("/api/trash").json()["items"])


# ============================================================== activity (cap 8)
def test_activity_records_write(client):
    client.post("/api/files/write", json={"path": "readme.txt", "content": "v2\n"})
    evs = client.get("/api/activity", params={"limit": 10}).json()["events"]
    assert any(e["action"] == "write" for e in evs)


def test_activity_records_delete(client):
    client.delete("/api/files", params={"path": "readme.txt"})
    evs = client.get("/api/activity", params={"limit": 10}).json()["events"]
    assert any(e["action"] == "delete" for e in evs)


def test_activity_newest_first_and_limit(client):
    for n in range(5):
        client.post("/api/files/write", json={"path": f"f{n}.txt", "content": "z\n"})
    evs = client.get("/api/activity", params={"limit": 3}).json()["events"]
    assert len(evs) <= 3
    times = [e["at"] for e in evs]
    assert times == sorted(times, reverse=True)
