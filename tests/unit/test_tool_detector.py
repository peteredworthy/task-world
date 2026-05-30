"""Pure ToolDetector configuration tests.

These tests intentionally avoid ``ToolDetector.detect_all()``. Real host
detection is covered once through the integration agents API tests; unit
coverage here stays deterministic and does not inspect Docker, Codex, or PATH.
"""

from collections.abc import Sequence

from orchestrator.runners import (
    ToolDetector,
    select_preferred_codex_model,
    validate_codex_model_selection,
)
from orchestrator.runners.agent_detector import _codex_server_config_with_models  # pyright: ignore[reportPrivateUsage]


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


def test_cli_config_prefers_gpt53_when_deprecated_model_is_first() -> None:
    """Regression: gpt-5.2-codex first in list must not become the default."""
    schema = ToolDetector._cli_config_for_codex(  # pyright: ignore[reportPrivateUsage]
        "codex",
        ["gpt-5.2-codex", "gpt-5.3-codex"],
    )

    model = _field(schema, "model")

    assert getattr(model, "field_type") == "select"
    assert getattr(model, "options") == ["gpt-5.2-codex", "gpt-5.3-codex"]
    assert getattr(model, "default") == "gpt-5.3-codex"


def test_codex_server_config_prefers_gpt53_when_deprecated_model_is_first() -> None:
    """Regression: codex_server detection must not default to gpt-5.2-codex."""
    schema = _codex_server_config_with_models(["gpt-5.2-codex", "gpt-5.3-codex"])

    model = _field(schema, "model")

    assert getattr(model, "field_type") == "select"
    assert getattr(model, "options") == ["gpt-5.2-codex", "gpt-5.3-codex"]
    assert getattr(model, "default") == "gpt-5.3-codex"


def test_codex_server_config_all_models_offered_preferred_is_default() -> None:
    """All discovered models appear as options; only the default changes."""
    models = ["gpt-5.2-codex", "gpt-5.2", "gpt-5.3-codex"]
    schema = _codex_server_config_with_models(models)

    model = _field(schema, "model")

    assert getattr(model, "options") == models
    assert getattr(model, "default") == "gpt-5.3-codex"


def test_cli_config_no_preferred_model_falls_back_to_first() -> None:
    """When no preferred model is in the list, falls back to models[0]."""
    schema = ToolDetector._cli_config_for_codex(  # pyright: ignore[reportPrivateUsage]
        "codex",
        ["custom-model-a", "custom-model-b"],
    )

    model = _field(schema, "model")

    assert getattr(model, "default") == "custom-model-a"


# ---------------------------------------------------------------------------
# select_preferred_codex_model — regression tests for unsupported model defaults
# ---------------------------------------------------------------------------


def test_select_preferred_model_returns_none_when_only_unsupported() -> None:
    """Regression: if only gpt-5.2-codex is discoverable, return None (no default)."""
    result = select_preferred_codex_model(["gpt-5.2-codex"])
    assert result is None


def test_select_preferred_model_skips_unsupported_in_fallback() -> None:
    """Unsupported model before a valid one: valid model is selected."""
    result = select_preferred_codex_model(["gpt-5.2-codex", "custom-model-x"])
    assert result == "custom-model-x"


def test_select_preferred_model_prefers_known_model_over_custom() -> None:
    """Known-good preferred model beats any other candidate."""
    result = select_preferred_codex_model(["custom-model-x", "gpt-5.3-codex"])
    assert result == "gpt-5.3-codex"


def test_cli_config_no_default_when_only_unsupported_model() -> None:
    """CLI config model field has no default when only unsupported models are discovered."""
    schema = ToolDetector._cli_config_for_codex(  # pyright: ignore[reportPrivateUsage]
        "codex",
        ["gpt-5.2-codex"],
    )
    model = _field(schema, "model")
    # Field should be a select (model list is non-empty) but default must be None
    assert getattr(model, "field_type") == "select"
    assert getattr(model, "default") is None


def test_codex_server_config_no_default_when_only_unsupported_model() -> None:
    """Codex Server config model field has no default when only unsupported models are discovered."""
    schema = _codex_server_config_with_models(["gpt-5.2-codex"])
    model = _field(schema, "model")
    assert getattr(model, "field_type") == "select"
    assert getattr(model, "default") is None


# ---------------------------------------------------------------------------
# validate_codex_model_selection — known-unsupported model blocking
# ---------------------------------------------------------------------------


def test_validate_rejects_known_unsupported_model_even_in_available_list() -> None:
    """gpt-5.2-codex is always rejected, even when it appears in the available list."""
    result = validate_codex_model_selection("gpt-5.2-codex", ["gpt-5.2-codex"])
    assert result is not None
    assert "gpt-5.2-codex" in result
    assert "not supported" in result


def test_validate_rejects_known_unsupported_model_with_empty_list() -> None:
    """gpt-5.2-codex is rejected even when model discovery returned nothing."""
    result = validate_codex_model_selection("gpt-5.2-codex", [])
    assert result is not None
    assert "gpt-5.2-codex" in result


def test_validate_accepts_valid_model_in_available_list() -> None:
    """A model present in the available list and not deprecated passes validation."""
    result = validate_codex_model_selection("gpt-5.3-codex", ["gpt-5.3-codex"])
    assert result is None


def test_validate_accepts_unknown_model_when_list_is_empty() -> None:
    """Unknown models pass validation when the available list is empty (discovery failed)."""
    result = validate_codex_model_selection("some-custom-model", [])
    assert result is None


def test_validate_rejects_model_not_in_available_list() -> None:
    """A model not in the available list and not deprecated is rejected."""
    result = validate_codex_model_selection("unknown-model", ["gpt-5.3-codex"])
    assert result is not None
    assert "unknown-model" in result
