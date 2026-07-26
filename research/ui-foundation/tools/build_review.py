from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


BATCH_SIZE = 12


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    blocking: bool
    downstream_dependency_count: int
    authority_risk: int
    capability_impact: int


class ReviewPriority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    downstream_dependency_count: int = Field(ge=0)
    authority_risk: int = Field(ge=0, le=3)
    capability_impact: int = Field(ge=0, le=3)
    basis: str = Field(min_length=1)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"REVIEW_SOURCE_INVALID:{path}")
    return cast(dict[str, Any], value)


def _review_item(value: object, priority: ReviewPriority) -> ReviewItem:
    if not isinstance(value, dict):
        raise ValueError("REVIEW_ITEM_INVALID")
    item = cast(dict[str, Any], value)
    return ReviewItem.model_validate(
        {
            "id": item.get("id"),
            "blocking": item.get("blocking", False),
            "downstream_dependency_count": priority.downstream_dependency_count,
            "authority_risk": priority.authority_risk,
            "capability_impact": priority.capability_impact,
        }
    )


def _review_priorities(root: Path) -> dict[str, ReviewPriority]:
    document = _load_yaml(root / "catalog/review-priorities.yaml")
    methodology = document.get("methodology")
    raw_items = document.get("items")
    if (
        not isinstance(methodology, (str, dict))
        or not methodology
        or not isinstance(raw_items, list)
    ):
        raise ValueError("REVIEW_PRIORITY_CATALOG_INVALID")
    priorities: dict[str, ReviewPriority] = {}
    for value in cast(list[Any], raw_items):
        try:
            priority = ReviewPriority.model_validate(value)
        except ValidationError as error:
            raise ValueError("REVIEW_PRIORITY_INVALID") from error
        if priority.id in priorities:
            raise ValueError(f"REVIEW_PRIORITY_DUPLICATE:{priority.id}")
        priorities[priority.id] = priority
    return priorities


def select_review_items(root: Path) -> list[list[ReviewItem]]:
    document = _load_yaml(root / "catalog/questions.yaml")
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("REVIEW_ITEMS_INVALID")
    item_values = cast(list[Any], raw_items)
    unresolved: dict[str, dict[str, Any]] = {}
    for value in item_values:
        if not isinstance(value, dict):
            raise ValueError("REVIEW_ITEM_INVALID")
        question = cast(dict[str, Any], value)
        identifier = question.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("REVIEW_ITEM_INVALID")
        if question.get("status") == "resolved":
            continue
        if identifier in unresolved:
            raise ValueError(f"REVIEW_QUESTION_DUPLICATE:{identifier}")
        unresolved[identifier] = question
    priorities = _review_priorities(root)
    missing = sorted(set(unresolved) - set(priorities))
    if missing:
        raise ValueError(f"REVIEW_PRIORITY_MISSING:{missing[0]}")
    extra = sorted(set(priorities) - set(unresolved))
    if extra:
        raise ValueError(f"REVIEW_PRIORITY_EXTRA:{extra[0]}")
    items = sorted(
        (
            _review_item(question, priorities[identifier])
            for identifier, question in unresolved.items()
        ),
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
    rendered: list[tuple[str, str]] = []
    for number, batch in enumerate(select_review_items(root), start=1):
        name = f"batch-{number:02d}.html"
        articles = "\n".join(
            f'<article data-item-id="{escape(item.id)}"><h2>{escape(item.id)}</h2>'
            f"<p>Blocking: {str(item.blocking).lower()}</p></article>"
            for item in batch
        )
        rendered.append(
            (
                name,
                '<!doctype html><html><head><meta charset="utf-8"><title>Foundation review</title>'
                f'</head><body data-source-snapshot="{escape(snapshot)}">{articles}</body></html>\n',
            )
        )
    output = root / "reviews"
    output.mkdir(parents=True, exist_ok=True)
    desired = {name for name, _content in rendered}
    for obsolete in output.glob("batch-[0-9][0-9].html"):
        if obsolete.name not in desired:
            obsolete.unlink()
    paths: list[Path] = []
    for name, content in rendered:
        path = output / name
        path.write_text(content, encoding="utf-8")
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
