from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict


BATCH_SIZE = 12


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    blocking: bool
    downstream_dependency_count: int
    authority_risk: int
    capability_impact: int


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"REVIEW_SOURCE_INVALID:{path}")
    return cast(dict[str, Any], value)


def _review_item(value: object) -> ReviewItem:
    if not isinstance(value, dict):
        raise ValueError("REVIEW_ITEM_INVALID")
    item = cast(dict[str, Any], value)
    affected = item.get("affected_ids", [])
    affected_ids = cast(list[Any], affected) if isinstance(affected, list) else []
    return ReviewItem.model_validate(
        {
            "id": item.get("id"),
            "blocking": item.get("blocking", False),
            "downstream_dependency_count": item.get(
                "downstream_dependency_count", len(affected_ids)
            ),
            "authority_risk": item.get(
                "authority_risk",
                sum(str(identifier).startswith("PER-") for identifier in affected_ids),
            ),
            "capability_impact": item.get(
                "capability_impact",
                sum(str(identifier).startswith("CAP-") for identifier in affected_ids),
            ),
        }
    )


def select_review_items(root: Path) -> list[list[ReviewItem]]:
    document = _load_yaml(root / "catalog/questions.yaml")
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("REVIEW_ITEMS_INVALID")
    item_values = cast(list[Any], raw_items)
    items = sorted(
        (_review_item(value) for value in item_values),
        key=lambda item: (
            not item.blocking,
            -item.downstream_dependency_count,
            -item.authority_risk,
            -item.capability_impact,
            item.id,
        ),
    )
    blockers = [item for item in items if item.blocking]
    selected = blockers or items[:BATCH_SIZE]
    return [selected[index : index + BATCH_SIZE] for index in range(0, len(selected), BATCH_SIZE)]


def build_review(root: Path) -> list[Path]:
    evidence = _load_yaml(root / "catalog/evidence.yaml")
    snapshot = evidence.get("active_snapshot_id")
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError("ACTIVE_SNAPSHOT_INVALID")
    output = root / "reviews"
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for number, batch in enumerate(select_review_items(root), start=1):
        path = output / f"batch-{number:02d}.html"
        articles = "\n".join(
            f'<article data-item-id="{escape(item.id)}"><h2>{escape(item.id)}</h2>'
            f"<p>Blocking: {str(item.blocking).lower()}</p></article>"
            for item in batch
        )
        path.write_text(
            '<!doctype html><html><head><meta charset="utf-8"><title>Foundation review</title>'
            f'</head><body data-source-snapshot="{escape(snapshot)}">{articles}</body></html>\n',
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("research/ui-foundation"))
    args = parser.parse_args()
    for path in build_review(args.root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
