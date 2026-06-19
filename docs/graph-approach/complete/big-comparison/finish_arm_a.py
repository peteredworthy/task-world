import json
from arm_a_graph import builder, verifier, record, RETRY_LIMIT
# Region 5 = the quota + activity capabilities the horizon planner (plan5) itself produced.
region = "Section 6 (Quota) + Section 8 (Activity log) + purge interaction"
steps = [
  "Implement GET/POST /api/quota: default max_bytes=1000000; GET returns {max_bytes,used_bytes,available_bytes} where used_bytes = sum of live file sizes (exclude .meta, versions, trash); POST {max_bytes} updates it; persist under desktop_fs/.meta/.",
  "Enforce quota: write/copy/restore(trash or version) that would exceed max_bytes returns 413 {\"detail\":\"quota exceeded\"} and makes NO change (no partial write, no version snapshot, no trash mutation). Trash/version bytes never count toward live usage.",
  "Implement activity log: bounded ring (>=100 newest) under .meta; GET /api/activity?limit=<n> newest-first returning {events:[{action,path,at(iso8601)}]}; emit on write,delete,restore,rename,move,copy,version_restore,tag,purge.",
  "Ensure purge of a trash entry also drops its version history and tags (clean slate if the path is recreated).",
]
verify = "Add tests for quota defaults/set/enforcement (413, no side effects, versions&trash excluded), activity payload/order/limit, and purge dropping versions+tags. Run `uv run pytest -q`."
correction = ""
for attempt in range(1, RETRY_LIMIT + 1):
    builder(5, region, steps, verify, correction)
    ver = verifier(5, region, steps, verify)
    print("VERIFY 5.%d:" % attempt, ver)
    if ver.get("pass"):
        record(5, region, steps, f"verified on attempt {attempt} (completion of planned horizon 5)")
        break
    correction = ver.get("correction","") or "tests failed; re-check region intent"
else:
    record(5, region, steps, "NOT verified after retries")
print("DONE arm A horizon 5")
