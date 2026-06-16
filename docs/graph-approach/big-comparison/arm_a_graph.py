"""Arm A — Graph approach (recursive horizon planning).

The defining mechanism of the task-world execution graph (evaluation §6.1): a planner emits
ONE patch = an executable *region* covering the next horizon (several build+verify steps
that can be planned without predicting what implementation will discover) PLUS a successor
planner. The loop is graph readiness: build the region, verify it, then the successor planner
replans the next horizon from the accumulated immutable facts.

Modelled here as: few planning turns, each planning a multi-step region; batch build + an
independent structural verifier per region; immutable verified facts in STATE.md.
This sits between idea-to-plan (one plan, all up front) and mind-the-gap (one chunk at a time).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from driver_common import arm_totals, run_codex

ARM = "A-graph"
ARMDIR = Path("/Users/peter/code/comparison-arms/arm-a")
STATE = ARMDIR / "STATE.md"
MAX_HORIZONS = 5
RETRY_LIMIT = 3


def parse_verdict(text: str) -> dict:
    m = list(re.finditer(r"VERDICT:\s*(\{.*\})\s*$", text, re.S | re.M))
    if not m:
        m = list(re.finditer(r"(\{.*\})\s*$", text.strip(), re.S))
    for cand in reversed(m):
        try:
            return json.loads(cand.group(1))
        except json.JSONDecodeError:
            continue
    return {}


def planner(n: int) -> dict:
    prompt = f"""You are the HORIZON PLANNER for a graph-structured build. Read SPEC.md (full
requirements) and STATE.md (regions already built and verified). Inspect current code.

Plan the NEXT HORIZON: a coherent REGION of work — typically 2-4 related build steps — that
can be fully specified now without needing to discover implementation details first. Plan a
batch, not a single tiny chunk, and not the whole project. Treat already-verified regions as
immutable; build on them. If everything in SPEC.md is implemented and verified, set done=true.

End with one line:
VERDICT: {{"done": false, "region": "<name>", "steps": ["step 1", "step 2", "..."], "verify": "<how the whole region is verified, incl tests>"}}
(or {{"done": true}}). This is horizon #{n}."""
    rec = run_codex(ARM, f"plan{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=1000)
    return parse_verdict(rec["last_msg"])


def builder(n: int, region: str, steps: list, verify: str, correction: str = "") -> None:
    corr = f"\n\nThe verifier rejected the previous attempt. Fix specifically:\n{correction}" if correction else ""
    steps_txt = "\n".join(f"  - {s}" for s in steps)
    prompt = f"""You are the BUILDER. Implement this entire REGION in the existing FastAPI app,
keeping all existing endpoints and previously-verified regions working:

REGION: {region}
STEPS:
{steps_txt}
HOW IT WILL BE VERIFIED: {verify}

Implement all steps of the region together, add/extend tests under tests/, and run
`uv run pytest -q`. Metadata persists under desktop_fs/.meta/ and must never appear in
listings or search.{corr} When done, print what you changed and the pytest result."""
    run_codex(ARM, f"build{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=2400)


def verifier(n: int, region: str, steps: list, verify: str) -> dict:
    steps_txt = "\n".join(f"  - {s}" for s in steps)
    prompt = f"""You are the VERIFIER NODE — independent. Do NOT modify source files; only run
tests/commands and inspect. Check that this whole region is correctly and completely built
against its intent:

REGION: {region}
STEPS:
{steps_txt}
VERIFY: {verify}

Run `uv run pytest -q`. The region passes only if relevant tests pass AND behavior matches
intent (tests must not assert obsolete behavior). End with one line:
VERDICT: {{"pass": true_or_false, "correction": "<specific fixes if failing, else empty>"}}"""
    rec = run_codex(ARM, f"verify{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=1500)
    return parse_verdict(rec["last_msg"])


def record(n: int, region: str, steps: list, evidence: str) -> None:
    steps_txt = "\n".join(f"  - {s}" for s in steps)
    with open(STATE, "a") as f:
        f.write(f"\n## Horizon {n} — region '{region}' VERIFIED\n{steps_txt}\n- evidence: {evidence}\n")


def main() -> None:
    if not STATE.exists():
        STATE.write_text("# Verified regions (graph durable state)\n")
    for n in range(1, MAX_HORIZONS + 1):
        v = planner(n)
        print(f"HORIZON {n}: {v}")
        if v.get("done") or not v.get("steps"):
            print("Planner reports graph complete.")
            break
        region, steps, verify = v.get("region", f"region{n}"), v["steps"], v.get("verify", "")
        correction = ""
        for attempt in range(1, RETRY_LIMIT + 1):
            builder(n, region, steps, verify, correction)
            ver = verifier(n, region, steps, verify)
            print(f"  VERIFY {n}.{attempt}: {ver}")
            if ver.get("pass"):
                record(n, region, steps, f"verified on attempt {attempt}")
                break
            correction = ver.get("correction", "") or "tests failed; re-check region intent"
        else:
            record(n, region, steps, f"NOT verified after {RETRY_LIMIT} attempts; moving on")
    print("ARM A TOTALS", arm_totals(ARM))


if __name__ == "__main__":
    sys.exit(main())
