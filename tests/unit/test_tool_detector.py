"""Pure ToolDetector configuration tests.

These tests intentionally avoid ``ToolDetector.detect_all()``. Real host
detection is covered once through the integration agents API tests; unit
coverage here stays deterministic and does not inspect Docker, Codex, or PATH.
"""

from collections.abc import Sequence

from orchestrator.runners import ToolDetector


def _field(schema: Sequence[object], name: str) -> object:
    return next(field for field in schema if getattr(field, "name") == name)


def test_cli_config_uses_plain_model_field_without_discovered_models() -> None:
    schema = ToolDetector._cli_config_for_codex("codex", [])  # pyright: ignore[reportPrivateUsage]

    command = _field(schema, "command")
    model = _field(schema, "model")

    assert getattr(command, "default") == "codex"
    assert getattr(model, "field_type") == "string"
    assert getattr(model, "options") is None


def test_cli_config_uses_select_model_field_with_discovered_models() -> None:
    schema = ToolDetector._cli_config_for_codex(  # pyright: ignore[reportPrivateUsage]
        "codex",
        ["gpt-5.3-codex", "gpt-5.2"],
    )

    command = _field(schema, "command")
    model = _field(schema, "model")

    assert getattr(command, "default") == "codex"
    assert getattr(model, "field_type") == "select"
    assert getattr(model, "options") == ["gpt-5.3-codex", "gpt-5.2"]
    assert getattr(model, "default") == "gpt-5.3-codex"
