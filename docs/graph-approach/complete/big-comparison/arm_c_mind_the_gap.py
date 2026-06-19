"""Arm C — Mind-the-gap. Repeated planner/gap-finder -> builder -> validator cycles.

The orchestrator (this script) owns durable state in STATE.md. Each chunk uses fresh
builder and validator agents. A chunk is verified only when its tests pass. Default retry
limit 5; planner-chunk cap bounds the loop.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from driver_common import arm_totals, run_codex

ARM = "C-mind-the-gap"
ARMDIR = Path("/Users/peter/code/comparison-arms/arm-c")
STATE = ARMDIR / "STATE.md"
MAX_CHUNKS = 9
RETRY_LIMIT = 5


def parse_verdict(text: str) -> dict:
    """Pull the last JSON object following a VERDICT: marker (or any trailing {...})."""
    m = list(re.finditer(r"VERDICT:\s*(\{.*?\})\s*$", text, re.S | re.M))
    if not m:
        m = list(re.finditer(r"(\{[^{}]*\})\s*$", text.strip(), re.S))
    if not m:
        return {}
    try:
        return json.loads(m[-1].group(1))
    except json.JSONDecodeError:
        return {}


def planner(n: int) -> dict:
    prompt = f"""You are the PLANNER / GAP-FINDER. Read SPEC.md (full requirements) and
STATE.md (verified work so far). Inspect the current code. Compare the target with the
verified state and pick the NEXT single small, independently-verifiable chunk of work — the
most valuable gap to close next. Do not implement it. Keep chunks small enough that one
builder can finish and one validator can check them. If the entire spec is already
implemented and verified, set done=true.
End your message with one line:
VERDICT: {{"done": false, "chunk": "<what to build next>", "verify": "<how to verify it, incl. which tests>"}}
(or {{"done": true}} if nothing remains). This is chunk #{n}."""
    rec = run_codex(ARM, f"plan{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=900)
    return parse_verdict(rec["last_msg"])


def builder(n: int, chunk: str, verify: str, correction: str = "") -> None:
    corr = f"\n\nA previous attempt failed validation. Fix this specifically:\n{correction}" if correction else ""
    prompt = f"""You are the BUILDER. Implement ONLY this chunk in the existing FastAPI app,
keeping all existing endpoints and previously-verified behavior working:

CHUNK: {chunk}
HOW IT WILL BE VERIFIED: {verify}

Add/extend tests under tests/ for this chunk and run `uv run pytest -q`. Metadata persists
under desktop_fs/.meta/ and must never appear in listings or search. Do not implement other
chunks.{corr} When done, print what you changed and the pytest result."""
    run_codex(ARM, f"build{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=1800)


def validator(n: int, chunk: str, verify: str) -> dict:
    prompt = f"""You are the VALIDATOR — independent reviewer. Do NOT modify source files
(main.py/modules); you may only run tests/commands and inspect. Check that this chunk is
correctly and completely implemented against its criteria:

CHUNK: {chunk}
VERIFY: {verify}

Run `uv run pytest -q`. A chunk is valid only if the relevant tests pass AND the behavior
matches the chunk's intent (tests must not assert obsolete/wrong behavior).
End your message with one line:
VERDICT: {{"pass": true_or_false, "correction": "<specific fix instruction if failing, else empty>"}}"""
    rec = run_codex(ARM, f"valid{n}", prompt, ARMDIR, sandbox="workspace-write", timeout=1200)
    return parse_verdict(rec["last_msg"])


def record(n: int, chunk: str, evidence: str) -> None:
    line = f"\n## Chunk {n} — VERIFIED\n- {chunk}\n- evidence: {evidence}\n"
    with open(STATE, "a") as f:
        f.write(line)


def main() -> None:
    if not STATE.exists():
        STATE.write_text("# Verified state (mind-the-gap durable log)\n")
    for n in range(1, MAX_CHUNKS + 1):
        v = planner(n)
        print(f"PLAN {n}: {v}")
        if v.get("done") or not v.get("chunk"):
            print("Planner reports complete.")
            break
        chunk, verify = v["chunk"], v.get("verify", "")
        correction = ""
        for attempt in range(1, RETRY_LIMIT + 1):
            builder(n, chunk, verify, correction)
            ver = validator(n, chunk, verify)
            print(f"  VALIDATE {n}.{attempt}: {ver}")
            if ver.get("pass"):
                record(n, chunk, f"validated on attempt {attempt}")
                break
            correction = ver.get("correction", "") or "tests failed; re-check the chunk criteria"
        else:
            record(n, chunk, f"NOT validated after {RETRY_LIMIT} attempts; escalating, moving on")
    print("ARM C TOTALS", arm_totals(ARM))


if __name__ == "__main__":
    sys.exit(main())
