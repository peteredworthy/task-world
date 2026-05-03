"""Unit tests for ModelProfile enum and agent runner model default resolution."""

import pytest

from orchestrator.config import ModelProfile
from orchestrator.runners import resolve_model_for_profile


class TestModelProfileEnum:
    def test_all_profiles_exist(self) -> None:
        values = {p.value for p in ModelProfile}
        assert values == {"architect", "designer", "coder", "summarizer"}

    def test_profiles_are_str_enum(self) -> None:
        for profile in ModelProfile:
            assert isinstance(profile, str)

    def test_profile_value_lookup(self) -> None:
        assert ModelProfile("architect") == ModelProfile.ARCHITECT
        assert ModelProfile("designer") == ModelProfile.DESIGNER
        assert ModelProfile("coder") == ModelProfile.CODER
        assert ModelProfile("summarizer") == ModelProfile.SUMMARIZER

    def test_invalid_profile_raises(self) -> None:
        with pytest.raises(ValueError):
            ModelProfile("unknown")


class TestResolveModelForProfile:
    def test_returns_profile_default_when_profile_matches(self) -> None:
        model_defaults = {"coder": "claude-sonnet-4-6", "architect": "claude-opus-4-6"}
        result = resolve_model_for_profile(
            ModelProfile.CODER,
            model_defaults,
            fallback_model="gpt-4o",
        )
        assert result == "claude-sonnet-4-6"

    def test_falls_back_to_fallback_model_when_no_profile_default(self) -> None:
        model_defaults: dict[str, str] = {}
        result = resolve_model_for_profile(
            ModelProfile.ARCHITECT,
            model_defaults,
            fallback_model="gpt-4o",
        )
        assert result == "gpt-4o"

    def test_falls_back_to_fallback_model_when_profile_not_in_defaults(self) -> None:
        model_defaults = {"coder": "claude-sonnet-4-6"}
        result = resolve_model_for_profile(
            ModelProfile.ARCHITECT,
            model_defaults,
            fallback_model="gpt-4o",
        )
        assert result == "gpt-4o"

    def test_returns_none_when_no_profile_and_no_fallback(self) -> None:
        result = resolve_model_for_profile(
            None,
            {},
        )
        assert result is None

    def test_returns_fallback_when_no_profile(self) -> None:
        model_defaults = {"coder": "claude-sonnet-4-6"}
        result = resolve_model_for_profile(
            None,
            model_defaults,
            fallback_model="gpt-4o",
        )
        assert result == "gpt-4o"

    def test_profile_default_takes_precedence_over_fallback(self) -> None:
        model_defaults = {"summarizer": "claude-haiku-4-5"}
        result = resolve_model_for_profile(
            ModelProfile.SUMMARIZER,
            model_defaults,
            fallback_model="gpt-4o",
        )
        assert result == "claude-haiku-4-5"

    def test_all_profiles_can_be_resolved(self) -> None:
        model_defaults = {
            "architect": "model-a",
            "designer": "model-b",
            "coder": "model-c",
            "summarizer": "model-d",
        }
        assert resolve_model_for_profile(ModelProfile.ARCHITECT, model_defaults) == "model-a"
        assert resolve_model_for_profile(ModelProfile.DESIGNER, model_defaults) == "model-b"
        assert resolve_model_for_profile(ModelProfile.CODER, model_defaults) == "model-c"
        assert resolve_model_for_profile(ModelProfile.SUMMARIZER, model_defaults) == "model-d"

    def test_returns_none_when_no_fallback_and_no_match(self) -> None:
        model_defaults = {"coder": "some-model"}
        result = resolve_model_for_profile(
            ModelProfile.ARCHITECT,
            model_defaults,
            fallback_model=None,
        )
        assert result is None
