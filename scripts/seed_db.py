"""Obsolete development database seeding entrypoint.

The previous implementation wrote run snapshots through removed pre-events_v2
APIs. Seed data now needs to be created through the same service/API lifecycle
used by real runs so events_v2, the JSONL outbox, and projections stay in sync.

Maintained alternatives:
    uv run orchestrator run create <routine> --project <path> --config '<json>'
    curl -X POST http://localhost:8000/api/runs ...
"""

from __future__ import annotations


MESSAGE = (
    "scripts/seed_db.py is obsolete. Create development data through the "
    "orchestrator CLI or REST API so events_v2 and projections remain consistent."
)


def main() -> None:
    raise SystemExit(MESSAGE)


if __name__ == "__main__":
    main()
