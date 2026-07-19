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


def test_owner_proof_does_not_leak_across_scopes_or_before_assignment() -> None:
    source = """\
def first():
    usage = ModelTokenUsage(input_tokens=1)
    return usage.input_tokens

def second(usage):
    return usage.input_tokens

def third():
    before = usage.input_tokens
    usage = ModelTokenUsage(input_tokens=1)
    return before
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "return usage.gen_ai_usage_input_tokens" in transformed
    assert transformed.count("usage.input_tokens") == 2
    diagnostics = diagnose_source(source, path="src/orchestrator/state/models.py")
    assert len(diagnostics) == 2


def test_explicit_repository_contracts_are_proven_without_suffix_matching() -> None:
    source = """\
class TurnMetrics:
    input_tokens: int
class SubAgentLog:
    output_tokens: int
class ActionLog:
    cache_read_tokens: int
class AttemptMetrics:
    tokens_read: int

turn = TurnMetrics(input_tokens=1)
log = SubAgentLog(output_tokens=2)
action = ActionLog(cache_read_tokens=3)
attempt = AttemptMetrics(tokens_read=4)
total = turn.input_tokens + log.output_tokens + action.cache_read_tokens + attempt.tokens_read
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "gen_ai_usage_input_tokens: int" in transformed
    assert "TurnMetrics(gen_ai_usage_input_tokens=1)" in transformed
    assert "turn.gen_ai_usage_input_tokens" in transformed
    assert "attempt.gen_ai_usage_input_tokens" in transformed


def test_annotated_telemetry_assignment_proves_later_attribute() -> None:
    source = """\
usage: ModelTokenUsage = ModelTokenUsage(input_tokens=1)
total = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "usage.gen_ai_usage_input_tokens" in transformed
    assert diagnose_source(source, path="src/orchestrator/state/models.py") == ()


def test_provider_cache_read_tokens_is_preserved_at_parser_boundary() -> None:
    source = 'a = payload.get("cache_read_tokens")\nb = payload["cache_read_tokens"]\n'

    assert (
        transform_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == source
    )
    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == ()


def test_telemetry_dictionary_preserves_prefixed_and_triple_quoted_literals() -> None:
    source = '''payload = ModelTokenUsage.model_validate({r"input_tokens": 1, """output_tokens""": 2})\n'''

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert 'r"gen_ai_usage_input_tokens"' in transformed
    assert '"""gen_ai_usage_output_tokens"""' in transformed


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


def test_rebinding_and_conditional_ownership_are_diagnostic() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
usage = object()
after = usage.input_tokens
if enabled:
    conditional = ModelTokenUsage(input_tokens=1)
later = conditional.input_tokens
"""
    transformed = transform_source(source, path="src/orchestrator/state/models.py")
    assert "after = usage.input_tokens" in transformed
    assert "later = conditional.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 2


def test_same_line_owner_precedes_attribute() -> None:
    source = "usage = ModelTokenUsage(input_tokens=1); total = usage.input_tokens\n"
    assert "usage.gen_ai_usage_input_tokens" in transform_source(
        source, path="src/orchestrator/state/models.py"
    )


def test_additional_repository_contracts_are_explicitly_proven() -> None:
    source = """\
class ExecutionMetrics: input_tokens: int
class GatekeeperVerdictCommandRow: input_tokens: int
class GatekeeperCostCommandRow: input_tokens: int
class GatekeeperVerdictRow: input_tokens: int
class GatekeeperCostRecordedPayload: input_tokens: int
value = ExecutionMetrics(input_tokens=1).input_tokens
"""
    assert (
        transform_source(source, path="src/orchestrator/state/models.py").count(
            "gen_ai_usage_input_tokens"
        )
        == 7
    )
    assert (
        "ExecutionMetrics(gen_ai_usage_input_tokens=1).gen_ai_usage_input_tokens"
        in transform_source(source, path="src/orchestrator/state/models.py")
    )
    assert diagnose_source(source, path="src/orchestrator/state/models.py") == ()


def test_unknown_parser_receiver_is_diagnostic() -> None:
    source = 'raw = unknown.get("cache_read_tokens")\n'
    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py")


def test_annassign_kills_a_preceding_telemetry_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
usage: object = object()
total = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")
    assert "total = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_match_case_telemetry_assignment_is_not_proven_after_the_match() -> None:
    source = """\
match event:
    case {"usage": usage}:
        usage = ModelTokenUsage(input_tokens=1)
total = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")
    assert "total = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_proven_use_before_a_later_kill_is_still_rewritten() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
before = usage.input_tokens
usage = object()
after = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "before = usage.gen_ai_usage_input_tokens" in transformed
    assert "after = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_inner_scope_owner_is_unconditional_despite_outer_conditional() -> None:
    source = """\
if enabled:
    def collect():
        usage = ModelTokenUsage(input_tokens=1)
        return usage.input_tokens

    class Collector:
        usage = ModelTokenUsage(input_tokens=1)
        total = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "return usage.gen_ai_usage_input_tokens" in transformed
    assert "total = usage.gen_ai_usage_input_tokens" in transformed
    assert diagnose_source(source, path="src/orchestrator/state/models.py") == ()


def test_provider_subscripts_require_an_explicit_provider_receiver() -> None:
    source = 'unknown = unknown["cache_read_tokens"]\nknown = payload["cache_read_tokens"]\n'

    assert (
        transform_source(source, path="src/orchestrator/runners/agents/codex/parser.py") == source
    )
    diagnostics = diagnose_source(source, path="src/orchestrator/runners/agents/codex/parser.py")
    assert len(diagnostics) == 1
    assert "cache_read_tokens" in diagnostics[0]


def test_remaining_explicit_accounting_contracts_are_proven() -> None:
    source = """\
class TurnMetricsSchema: input_tokens: int
class ActionLogSchema: total_output_tokens: int
class GatekeeperVerdict: cache_read_tokens: int
class MockBehavior: tokens_write: int
verdict = GatekeeperVerdict(cache_read_tokens=1)
value = verdict.cache_read_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert transformed.count("gen_ai_usage_input_tokens") == 1
    assert transformed.count("gen_ai_usage_output_tokens") == 2
    assert transformed.count("gen_ai_usage_cache_read_input_tokens") == 3


def test_assignment_owner_activates_after_its_rhs_is_evaluated() -> None:
    source = """\
usage = provider
usage = ModelTokenUsage(input_tokens=usage.input_tokens)
later = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "input_tokens=usage.input_tokens" in transformed
    assert "later = usage.gen_ai_usage_input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_tuple_rebinding_kills_a_telemetry_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
usage, [*others] = providers
later = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "later = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_binding_control_targets_invalidate_a_stale_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
for usage in providers:
    during_for = usage.input_tokens
after_for = usage.input_tokens
with provider as usage:
    during_with = usage.input_tokens
after_with = usage.input_tokens
marker = (usage := provider)
after_named_expression = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "during_for = usage.input_tokens" in transformed
    assert "after_for = usage.input_tokens" in transformed
    assert "during_with = usage.input_tokens" in transformed
    assert "after_with = usage.input_tokens" in transformed
    assert "after_named_expression = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 5


def test_match_mapping_pattern_binding_invalidates_a_stale_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
match provider:
    case {"usage": usage}:
        inside_case = usage.input_tokens
after_case = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "inside_case = usage.input_tokens" in transformed
    assert "after_case = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 2


def test_nested_match_sequence_star_and_or_bindings_invalidate_a_stale_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
match provider:
    case {"outer": [*usage]} | [*usage]:
        inside_case = usage.input_tokens
after_case = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "inside_case = usage.input_tokens" in transformed
    assert "after_case = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 2


def test_for_target_uncertainty_starts_after_iterable_evaluation() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
for usage in [usage.input_tokens]:
    inside_loop = usage.input_tokens
after_loop = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "[usage.gen_ai_usage_input_tokens]" in transformed
    assert "inside_loop = usage.input_tokens" in transformed
    assert "after_loop = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 2


def test_augassign_invalidates_a_stale_owner_after_its_evaluation() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
usage += replacement
after_augassign = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "after_augassign = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1


def test_exception_alias_invalidates_a_stale_owner_in_and_after_handler() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
try:
    raise Error()
except Error as usage:
    inside_handler = usage.input_tokens
after_handler = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "inside_handler = usage.input_tokens" in transformed
    assert "after_handler = usage.input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 2


def test_comprehension_binding_is_diagnostic_without_killing_outer_owner() -> None:
    source = """\
usage = ModelTokenUsage(input_tokens=1)
values = [usage.input_tokens for usage in providers]
after_comprehension = usage.input_tokens
"""

    transformed = transform_source(source, path="src/orchestrator/state/models.py")

    assert "[usage.input_tokens for usage in providers]" in transformed
    assert "after_comprehension = usage.gen_ai_usage_input_tokens" in transformed
    assert len(diagnose_source(source, path="src/orchestrator/state/models.py")) == 1
