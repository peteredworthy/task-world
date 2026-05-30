"""Obsolete helper for cloning legacy run snapshots from S2.

This script used to mutate projected run state directly to manufacture a new
run that started at S3. That bypasses the current events_v2 event log and is no
longer supported operational tooling.
"""

from __future__ import annotations


MESSAGE = (
    "scripts/clone_run_from_s2.py is obsolete. Create a new run through the "
    "orchestrator API/CLI and advance it through supported lifecycle commands "
    "so events_v2 and projections stay consistent."
)


def main() -> None:
    raise SystemExit(MESSAGE)


if __name__ == "__main__":
    main()
