"""Run child verification commands and maintain a run.evidence.v1 bundle.

This helper is intended for generated super-parent child routines. It keeps the
LLM out of command-output bookkeeping: each command is run once, a durable log is
written under `.evidence/`, and the structured evidence JSON is updated before
execution starts and after every command.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


OUTCOME_VALUES = (
    "verified_fix",
    "bug_not_reproduced",
    "behavior_already_correct",
    "environment_blocked",
    "needs_revision",
    "partial_progress",
    "unrelated_failure",
)
TARGET_BUG_REPRODUCED_VALUES = ("reproduced", "not_reproduced", "not_targeted", "unknown")
NEXT_RECOMMENDATION_VALUES = ("proceed", "replan", "stop", "environment_blocked")
EXCERPT_LIMIT = 2000


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: str


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    log_path: Path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cwd = Path(args.cwd).resolve()
    evidence_path = Path(args.evidence_path or f"docs/run-evidence/{args.slice_id}-evidence.json")
    evidence_path = _resolve_inside(cwd, evidence_path)
    evidence_dir = _resolve_inside(cwd, Path(args.evidence_dir))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)

    commands = [_parse_command(raw, index) for index, raw in enumerate(args.command, start=1)]
    bundle = _bundle(
        args=args,
        commands_run=[],
        test_results=[],
        files_changed=[],
        evidence_files=[_rel(cwd, evidence_path)],
        open_uncertainties=["Verification has started but has not completed."],
        outcome="partial_progress",
        next_recommendation="replan",
    )
    _write_json(evidence_path, bundle)

    results: list[CommandResult] = []
    for command in commands:
        result = _run_command(command, cwd=cwd, evidence_dir=evidence_dir)
        results.append(result)
        bundle = _completed_bundle(args=args, cwd=cwd, evidence_path=evidence_path, results=results)
        _write_json(evidence_path, bundle)
        if result.exit_code != 0 and args.stop_on_failure:
            break

    bundle = _completed_bundle(args=args, cwd=cwd, evidence_path=evidence_path, results=results)
    _write_json(evidence_path, bundle)

    failed = [result for result in results if result.exit_code != 0]
    print(f"run_child_evidence: wrote {evidence_path.relative_to(cwd)}")
    print(f"run_child_evidence: commands={len(results)} failed={len(failed)}")
    for result in failed:
        print(f"run_child_evidence: FAILED {result.name} exit_code={result.exit_code}")
        if result.stderr.strip():
            print(_excerpt(result.stderr))
        elif result.stdout.strip():
            print(_excerpt(result.stdout))
    return 1 if failed else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run verification commands and write a run.evidence.v1 bundle."
    )
    parser.add_argument("--slice-id", required=True)
    parser.add_argument("--routine-id", required=True)
    parser.add_argument("--evidence-path")
    parser.add_argument("--evidence-dir", default=".evidence")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--assumption", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--real-execution-surface", default="verification commands")
    parser.add_argument("--real-frontend-path-exercised", action="store_true")
    parser.add_argument(
        "--target-bug-reproduced",
        choices=TARGET_BUG_REPRODUCED_VALUES,
        default="not_targeted",
    )
    parser.add_argument("--success-outcome", choices=OUTCOME_VALUES, default="verified_fix")
    parser.add_argument("--failure-outcome", choices=OUTCOME_VALUES, default="needs_revision")
    parser.add_argument(
        "--success-next-recommendation",
        choices=NEXT_RECOMMENDATION_VALUES,
        default="proceed",
    )
    parser.add_argument(
        "--failure-next-recommendation",
        choices=NEXT_RECOMMENDATION_VALUES,
        default="replan",
    )
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Command to run. Use 'label::command' to control the log/test name.",
    )
    parser.add_argument("--expected-file-changed", action="append", default=[])
    parser.add_argument("--open-uncertainty", action="append", default=[])
    parser.add_argument("--stop-on-failure", action="store_true")
    parsed = parser.parse_args(argv)
    if not parsed.command:
        parser.error("at least one --command is required")
    return parsed


def _parse_command(raw: str, index: int) -> CommandSpec:
    if "::" in raw:
        name, command = raw.split("::", 1)
        name = name.strip()
        command = command.strip()
    else:
        name = f"command_{index}"
        command = raw.strip()
    if not name:
        raise SystemExit(f"--command #{index} has an empty label")
    if not command:
        raise SystemExit(f"--command #{index} has an empty command")
    return CommandSpec(name=name, command=command)


def _run_command(command: CommandSpec, *, cwd: Path, evidence_dir: Path) -> CommandResult:
    completed = subprocess.run(
        command.command,
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    log_path = evidence_dir / f"{_slug(command.name)}.log"
    log_path.write_text(
        "\n".join(
            [
                f"command: {command.command}",
                f"exit_code: {completed.returncode}",
                "--- stdout ---",
                completed.stdout,
                "--- stderr ---",
                completed.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return CommandResult(
        name=command.name,
        command=command.command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        log_path=log_path,
    )


def _completed_bundle(
    *,
    args: argparse.Namespace,
    cwd: Path,
    evidence_path: Path,
    results: list[CommandResult],
) -> dict[str, object]:
    failed = [result for result in results if result.exit_code != 0]
    outcome = args.failure_outcome if failed else args.success_outcome
    next_recommendation = (
        args.failure_next_recommendation if failed else args.success_next_recommendation
    )
    open_uncertainties = list(args.open_uncertainty)
    if failed:
        open_uncertainties.append("One or more verification commands failed.")
    files_changed = _files_changed(cwd, fallback=args.expected_file_changed)
    evidence_files = [_rel(cwd, result.log_path) for result in results]
    evidence_files.append(_rel(cwd, evidence_path))
    return _bundle(
        args=args,
        commands_run=[_command_entry(result) for result in results],
        test_results=[_test_result_entry(result) for result in results],
        files_changed=files_changed,
        evidence_files=evidence_files,
        open_uncertainties=open_uncertainties,
        outcome=outcome,
        next_recommendation=next_recommendation,
    )


def _bundle(
    *,
    args: argparse.Namespace,
    commands_run: list[dict[str, object]],
    test_results: list[dict[str, object]],
    files_changed: list[str],
    evidence_files: list[str],
    open_uncertainties: list[str],
    outcome: str,
    next_recommendation: str,
) -> dict[str, object]:
    summary = args.summary or (
        "Verification completed." if commands_run else "Verification evidence capture started."
    )
    assumption = args.assumption or f"Verification commands for {args.slice_id}"
    return {
        "schema_version": "run.evidence.v1",
        "slice_id": args.slice_id,
        "routine_id": args.routine_id,
        "assumption_tested": assumption,
        "summary": summary,
        "commands_run": commands_run,
        "test_results": test_results,
        "target_bug_reproduced": args.target_bug_reproduced,
        "real_frontend_path_exercised": bool(args.real_frontend_path_exercised),
        "real_execution_surface": args.real_execution_surface,
        "files_changed": files_changed,
        "evidence_files": sorted(dict.fromkeys(evidence_files)),
        "open_uncertainties": sorted(dict.fromkeys(open_uncertainties)),
        "next_recommendation": next_recommendation,
        "outcome": outcome,
    }


def _command_entry(result: CommandResult) -> dict[str, object]:
    return {
        "command": result.command,
        "exit_code": result.exit_code,
        "stdout_excerpt": _excerpt(result.stdout),
        "stderr_excerpt": _excerpt(result.stderr),
    }


def _test_result_entry(result: CommandResult) -> dict[str, object]:
    return {
        "name": result.name,
        "status": "passed" if result.exit_code == 0 else "failed",
        "details": f"exit_code={result.exit_code}; log={result.log_path}",
    }


def _files_changed(cwd: Path, *, fallback: list[str]) -> list[str]:
    result = subprocess.run(
        "git status --porcelain",
        cwd=cwd,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return sorted(dict.fromkeys(fallback))
    changed: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return sorted(dict.fromkeys(changed))


def _resolve_inside(cwd: Path, path: Path) -> Path:
    resolved = path if path.is_absolute() else cwd / path
    resolved = resolved.resolve()
    if cwd != resolved and cwd not in resolved.parents:
        raise SystemExit(f"path escapes cwd: {path}")
    return resolved


def _rel(cwd: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(cwd))
    except ValueError:
        return str(path)


def _write_json(path: Path, bundle: dict[str, object]) -> None:
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _excerpt(value: str) -> str:
    if len(value) <= EXCERPT_LIMIT:
        return value
    return value[:EXCERPT_LIMIT] + "\n...[truncated]"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-")
    return slug or "command"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
