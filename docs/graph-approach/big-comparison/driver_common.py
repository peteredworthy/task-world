"""Shared harness for the codex-driven arms (B idea-to-plan, C mind-the-gap).

Runs a codex agent non-interactively, captures the JSONL event stream, sums token
usage from `turn.completed` events, times wall-clock, persists a transcript, and
appends a structured record to metrics/<arm>.json. Pure stdlib.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
METRICS = HERE / "metrics"
MODEL = "gpt-5.3-codex-spark"

# GPT-5-class codex rates (USD per 1M tokens). ESTIMATE — spark pricing is not public
# and the user is on a subscription quota, so treat USD as indicative; token volume is
# the hard metric. Cached input billed at the cached rate.
RATES = {"input": 1.25, "cached": 0.125, "output": 10.0}


def usd(input_tokens: int, cached: int, output: int) -> float:
    billed_input = max(input_tokens - cached, 0)
    return round(
        billed_input / 1e6 * RATES["input"]
        + cached / 1e6 * RATES["cached"]
        + output / 1e6 * RATES["output"],
        4,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_codex(
    arm: str,
    role: str,
    prompt: str,
    armdir: str | Path,
    sandbox: str = "workspace-write",
    timeout: int = 1800,
) -> dict:
    """Run one codex agent. Returns a summary dict and appends it to metrics/<arm>.json."""
    METRICS.mkdir(exist_ok=True)
    armdir = Path(armdir)
    ts = datetime.now().strftime("%H%M%S")
    log_path = METRICS / f"{arm}_{role}_{ts}.jsonl"
    cmd = [
        "codex", "exec", "-m", MODEL, "--json",
        "-s", sandbox, "-C", str(armdir),
        "--dangerously-bypass-approvals-and-sandbox" if sandbox == "danger" else "--skip-git-repo-check",
        prompt,
    ]
    if sandbox == "danger":
        cmd = ["codex", "exec", "-m", MODEL, "--json", "-C", str(armdir),
               "--dangerously-bypass-approvals-and-sandbox", prompt]

    t0 = time.time()
    started = _now()
    usage = {"input": 0, "cached": 0, "output": 0, "reasoning": 0}
    turns = 0
    last_msg = ""
    tool_calls = 0
    with open(log_path, "w") as logf:
        proc = subprocess.run(
            cmd, cwd=str(armdir), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout,
        )
        logf.write(proc.stdout)
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type", "")
        if et == "turn.completed":
            turns += 1
            u = ev.get("usage", {})
            usage["input"] += u.get("input_tokens", 0)
            usage["cached"] += u.get("cached_input_tokens", 0)
            usage["output"] += u.get("output_tokens", 0)
            usage["reasoning"] += u.get("reasoning_output_tokens", 0)
        elif et == "item.completed":
            item = ev.get("item", {})
            if item.get("type") in ("command_execution", "file_change", "tool_call"):
                tool_calls += 1
            if item.get("type") == "agent_message":
                last_msg = item.get("text", "") or last_msg

    wall = round(time.time() - t0, 1)
    rec = {
        "arm": arm, "role": role, "started": started, "wall_s": wall,
        "turns": turns, "tool_calls": tool_calls,
        "tokens": usage,
        "usd_est": usd(usage["input"], usage["cached"], usage["output"] + usage["reasoning"]),
        "exit": proc.returncode, "log": log_path.name, "last_msg": last_msg[:4000],
    }
    mpath = METRICS / f"{arm}.json"
    data = json.loads(mpath.read_text()) if mpath.exists() else {"arm": arm, "calls": []}
    data["calls"].append(rec)
    mpath.write_text(json.dumps(data, indent=2))
    print(f"[{arm}/{role}] {wall}s turns={turns} tools={tool_calls} "
          f"tok(in={usage['input']} out={usage['output']} reason={usage['reasoning']}) "
          f"~${rec['usd_est']} exit={proc.returncode}")
    return rec


def arm_totals(arm: str) -> dict:
    mpath = METRICS / f"{arm}.json"
    if not mpath.exists():
        return {}
    data = json.loads(mpath.read_text())
    agg = {"calls": len(data["calls"]), "wall_s": 0.0, "turns": 0, "tool_calls": 0,
           "input": 0, "cached": 0, "output": 0, "reasoning": 0, "usd_est": 0.0}
    for c in data["calls"]:
        agg["wall_s"] += c["wall_s"]; agg["turns"] += c["turns"]
        agg["tool_calls"] += c["tool_calls"]; agg["usd_est"] += c["usd_est"]
        for k in ("input", "cached", "output", "reasoning"):
            agg[k] += c["tokens"][k]
    agg["wall_s"] = round(agg["wall_s"], 1)
    agg["usd_est"] = round(agg["usd_est"], 4)
    return agg
