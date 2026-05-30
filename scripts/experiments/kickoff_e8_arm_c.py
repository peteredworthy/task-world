"""Obsolete E8 Arm C kickoff helper.

The original experiment script cloned projected run rows and synthetic attempts
directly. That path is incompatible with the current events_v2 source of truth.
"""

from __future__ import annotations


MESSAGE = (
    "scripts/experiments/kickoff_e8_arm_c.py is obsolete. Recreate this "
    "experiment by creating a fresh run through the orchestrator API/CLI and "
    "driving state changes through supported lifecycle commands."
)


def main() -> None:
    raise SystemExit(MESSAGE)


if __name__ == "__main__":
    main()
