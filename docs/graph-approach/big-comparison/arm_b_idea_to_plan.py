"""Arm B — Idea-to-plan. Front-load a full plan, execute the whole plan, then verify.

Three fresh codex agents: PLAN -> IMPLEMENT -> VERIFY(+fix). The plan is authored up
front and not revised; verify fixes bugs but does not replan. That front-loading is the
defining trait of idea-to-plan.
"""

from __future__ import annotations

import sys

from driver_common import arm_totals, run_codex

ARM = "B-idea-to-plan"
ARMDIR = "/Users/peter/code/comparison-arms/arm-b"

PLAN = """You are the PLANNER. Read SPEC.md (the complete requirements for a Versioning +
Trash + Search feature in this FastAPI file-manager app). Do NOT write any implementation
code. Produce a thorough implementation plan and write it to PLAN.md, covering: module
layout, the on-disk metadata store design under desktop_fs/.meta/, data structures, every
endpoint's request/response contract and status codes, edge cases (retention, collision
rename, binary diff, persistence across restart), and a test plan. Be complete and concrete
so a separate engineer can implement it without further questions. Output only PLAN.md."""

IMPLEMENT = """You are the IMPLEMENTER. Read SPEC.md and PLAN.md. Implement the ENTIRE plan
now in one pass: edit main.py and add modules as the plan specifies, keeping all existing
endpoints working. Write the test suite under tests/ per the plan and run `uv run pytest -q`
until it passes. Metadata persists under desktop_fs/.meta/ and must never appear in listings
or search. `uv run python -c "import main"` must succeed. Follow the plan; do not redesign.
When done, print what you built and the pytest result."""

VERIFY = """You are the VERIFIER. Do NOT redesign. Read SPEC.md, then run `uv run pytest -q`
and exercise the app against the spec. If you find failing tests or spec violations, fix the
implementation bugs (not the design) until `uv run pytest -q` is green and the spec is met.
Keep existing endpoints working. End your message with a line:
VERDICT: {"green": true_or_false, "notes": "short summary"}"""


def main() -> None:
    run_codex(ARM, "plan", PLAN, ARMDIR, timeout=1800)
    run_codex(ARM, "implement", IMPLEMENT, ARMDIR, timeout=3000)
    run_codex(ARM, "verify", VERIFY, ARMDIR, timeout=2400)
    print("ARM B TOTALS", arm_totals(ARM))


if __name__ == "__main__":
    sys.exit(main())
