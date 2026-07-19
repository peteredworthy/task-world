"""Regression coverage for the R04 internal OTel vocabulary codemod."""

from scripts.codemods.r04_otel_vocab import (
    FIELD_RENAMES,
    diagnose_source,
    transform_source,
)


SAMPLE = """\
class Usage:
    input_tokens: int = 0  # retained comment
    output_tokens: int = 0

usage = Usage(input_tokens=1, output_tokens=2)
usage.input_tokens = 3
total = usage.input_tokens + usage.output_tokens
telemetry = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
"""


def test_model_usage_fields_are_renamed_without_touching_provider_keys() -> None:
    source = """
usage = ModelTokenUsage(input_tokens=1, output_tokens=2)
raw = payload.get("input_tokens")  # provider-boundary
total = usage.input_tokens + usage.output_tokens
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/agents/codex/parser.py",
    )

    assert "gen_ai_usage_input_tokens=1" in transformed
    assert "usage.gen_ai_usage_output_tokens" in transformed
    assert 'payload.get("input_tokens")' in transformed


def test_internal_telemetry_contracts_preserve_comments_and_formatting() -> None:
    transformed = transform_source(SAMPLE, path="src/orchestrator/state/models.py")

    assert "gen_ai_usage_input_tokens: int = 0  # retained comment" in transformed
    assert "Usage(gen_ai_usage_input_tokens=1, gen_ai_usage_output_tokens=2)" in transformed
    assert "usage.gen_ai_usage_input_tokens = 3" in transformed
    assert (
        'telemetry = {"gen_ai_usage_input_tokens": usage.gen_ai_usage_input_tokens, '
        '"gen_ai_usage_output_tokens": usage.gen_ai_usage_output_tokens}'
    ) in transformed


def test_second_pass_is_idempotent() -> None:
    once = transform_source(SAMPLE, path="src/orchestrator/state/models.py")

    assert transform_source(once, path="src/orchestrator/state/models.py") == once


def test_ambiguous_dictionary_key_is_reported_without_being_renamed() -> None:
    source = 'payload = {"input_tokens": 1}\n'

    assert transform_source(source, path="src/orchestrator/mystery.py") == source
    diagnostics = diagnose_source(source, path="src/orchestrator/mystery.py")
    assert len(diagnostics) == 1
    assert "input_tokens" in diagnostics[0]
    assert "ambiguous" in diagnostics[0]


def test_provider_raw_key_allowlist_is_explicit_and_preserves_wire_formats() -> None:
    source = """
usage = ModelTokenUsage(input_tokens=payload["inputTokens"])
raw = payload["reasoningOutputTokens"]
snake_case = payload.get("input_tokens")
provider_usage = {"input_tokens": 1, "output_tokens": 2}
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/agents/codex/parser.py",
    )

    assert 'gen_ai_usage_input_tokens=payload["inputTokens"]' in transformed
    assert 'payload["reasoningOutputTokens"]' in transformed
    assert 'payload.get("input_tokens")' in transformed
    assert 'provider_usage = {"input_tokens": 1, "output_tokens": 2}' in transformed
    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == ()
    assert FIELD_RENAMES["cache_read_tokens"] == "gen_ai_usage_cache_read_input_tokens"
