"""Regression coverage for the R04 internal OTel vocabulary codemod."""

import os
import subprocess
import sys
from pathlib import Path

from scripts.codemods.r04_otel_vocab import (
    FIELD_RENAMES,
    diagnose_source,
    transform_source,
)


SAMPLE = """\
class ModelTokenUsage:
    input_tokens: int = 0  # retained comment
    output_tokens: int = 0

usage = ModelTokenUsage(input_tokens=1, output_tokens=2)
usage.input_tokens = 3
total = usage.input_tokens + usage.output_tokens
telemetry = ModelTokenUsage.model_validate(
    {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
)
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
    assert (
        "ModelTokenUsage(gen_ai_usage_input_tokens=1, gen_ai_usage_output_tokens=2)" in transformed
    )
    assert "usage.gen_ai_usage_input_tokens = 3" in transformed
    assert (
        '{"gen_ai_usage_input_tokens": usage.gen_ai_usage_input_tokens, '
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
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/agents/codex/parser.py",
    )

    assert 'gen_ai_usage_input_tokens=payload["inputTokens"]' in transformed
    assert 'payload["reasoningOutputTokens"]' in transformed
    assert 'payload.get("input_tokens")' in transformed
    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == ()
    assert FIELD_RENAMES["cache_read_tokens"] == "gen_ai_usage_cache_read_input_tokens"


def test_unproven_owners_and_dictionaries_are_diagnostic_not_renamed() -> None:
    source = """\
class ProviderUsage:
    input_tokens: int

provider = ProviderUsage(input_tokens=1)
entry.metrics.input_tokens
verdict.input_tokens
payload = {"input_tokens": 1, "output_tokens": 2}
"""

    transformed = transform_source(source, path="src/orchestrator/mystery.py")

    assert transformed == source
    diagnostics = diagnose_source(source, path="src/orchestrator/mystery.py")
    assert len(diagnostics) == 6
    assert all("ambiguous" in diagnostic for diagnostic in diagnostics)


def test_internal_contract_owner_proves_nested_attribute_and_dictionary() -> None:
    source = """\
class ModelTokenUsage:
    input_tokens: int

entry.metrics = ModelTokenUsage(input_tokens=1)
total = entry.metrics.input_tokens
payload = ModelTokenUsage.model_validate({"input_tokens": 1, "output_tokens": 2})
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "entry.metrics.gen_ai_usage_input_tokens" in transformed
    assert '"gen_ai_usage_input_tokens": 1' in transformed
    assert diagnose_source(source, path="src/orchestrator/state/models.py") == ()


def test_provider_allowlist_only_exempts_boundary_extractions() -> None:
    source = """\
raw = payload.get("prompt_tokens")
cached = payload["cached_input_tokens"]
not_raw = {"input_tokens": 1}
"""

    assert (
        transform_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == source
    )
    diagnostics = diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py")
    assert len(diagnostics) == 1
    assert "input_tokens" in diagnostics[0]


def _run_cli(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {"PYTHONPATH": str(Path(__file__).parents[2])}
    return subprocess.run(
        [sys.executable, "-m", "scripts.codemods.r04_otel_vocab", mode],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_modes_report_apply_and_guard_changes(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "example.py"
    source_path.parent.mkdir()
    source_path.write_text("class ModelTokenUsage:\n    input_tokens: int\n")

    checked = _run_cli(tmp_path, "--check")
    assert checked.returncode == 0
    assert checked.stdout == "EDIT src/example.py\n"
    assert "input_tokens" in source_path.read_text()

    asserted = _run_cli(tmp_path, "--assert-clean")
    assert asserted.returncode == 1

    applied = _run_cli(tmp_path, "--apply")
    assert applied.returncode == 0
    assert "gen_ai_usage_input_tokens" in source_path.read_text()

    clean = _run_cli(tmp_path, "--assert-clean")
    assert clean.returncode == 0
    assert clean.stdout == ""


def test_cli_assert_clean_accepts_provider_boundary_extraction(tmp_path: Path) -> None:
    source_path = tmp_path / "src" / "orchestrator" / "runners" / "agents" / "codex" / "parser.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text('raw = payload.get("reasoningOutputTokens")\n')

    result = _run_cli(tmp_path, "--assert-clean")

    assert result.returncode == 0
