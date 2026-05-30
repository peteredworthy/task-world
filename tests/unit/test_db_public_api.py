"""Guardrails for the public orchestrator.db API."""

import pytest

import orchestrator.db as db

_EVENT_MODEL = "Event" + "Model"
_REPLAY_CHECKPOINT_MODEL = "Replay" + "Checkpoint" + "Model"
_CHECKPOINT_REPOSITORY = "Checkpoint" + "Repository"


@pytest.mark.parametrize(
    "name",
    [
        _EVENT_MODEL,
        "save_run",
        "update_latest_attempt",
        "update_parent_oversight_facts",
        _REPLAY_CHECKPOINT_MODEL,
        _CHECKPOINT_REPOSITORY,
    ],
)
def test_legacy_interfaces_are_not_public_db_exports(name: str) -> None:
    assert name not in db.__all__

    with pytest.raises(AttributeError):
        getattr(db, name)


@pytest.mark.parametrize(
    "name",
    [
        _EVENT_MODEL,
        "save_run",
        "update_latest_attempt",
        "update_parent_oversight_facts",
        _REPLAY_CHECKPOINT_MODEL,
        _CHECKPOINT_REPOSITORY,
    ],
)
def test_legacy_interfaces_are_not_importable_from_db(name: str) -> None:
    statement = f"from {'orchestrator'}.db import {name}"
    with pytest.raises(ImportError):
        exec(statement, {})


@pytest.mark.parametrize(
    ("module_name", "name"),
    [
        ("orchestrator.db.models", _EVENT_MODEL),
        ("orchestrator.db.models", _REPLAY_CHECKPOINT_MODEL),
        ("orchestrator.db.orm.models", _EVENT_MODEL),
        ("orchestrator.db.orm.models", _REPLAY_CHECKPOINT_MODEL),
        ("orchestrator.db.access.repositories", _CHECKPOINT_REPOSITORY),
    ],
)
def test_legacy_interfaces_are_not_importable_from_internal_modules(
    module_name: str,
    name: str,
) -> None:
    statement = f"from {module_name} import {name}"
    with pytest.raises(ImportError):
        exec(statement, {})
