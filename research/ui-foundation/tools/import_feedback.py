from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict


class CandidateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    response: str
    note: str
    source_snapshot: str


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("FEEDBACK_SCHEMA_INVALID: export must be an object")
    return cast(dict[str, Any], value)


def _active_snapshot(root: Path) -> str:
    evidence = yaml.safe_load((root / "catalog/evidence.yaml").read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    evidence_document = cast(dict[str, Any], evidence)
    snapshot = evidence_document.get("active_snapshot_id")
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    return snapshot


def import_feedback(root: Path, export_path: Path) -> list[CandidateDecision]:
    export = _load_json(export_path)
    schema = _load_json(root / "schemas/review-feedback.schema.json")
    validator = cast(Any, Draft202012Validator(schema, format_checker=FormatChecker()))
    errors: list[Any] = sorted(
        validator.iter_errors(export),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(f"FEEDBACK_SCHEMA_INVALID: {errors[0].message}")
    snapshot = _active_snapshot(root)
    if export["source_snapshot"] != snapshot:
        raise ValueError("FEEDBACK_SNAPSHOT_STALE")
    return [
        CandidateDecision(
            item_id=value["item_id"],
            response=value["response"],
            note=value["note"],
            source_snapshot=snapshot,
        )
        for value in export["response_history"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export_path", type=Path)
    parser.add_argument("--root", type=Path, default=Path("research/ui-foundation"))
    args = parser.parse_args()
    try:
        decisions = import_feedback(args.root, args.export_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps([decision.model_dump() for decision in decisions], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
