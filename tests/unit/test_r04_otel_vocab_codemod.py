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
    assert FIELD_RENAMES["tokens_reasoning"] == "gen_ai_usage_reasoning_output_tokens"
    assert FIELD_RENAMES["cache_write_tokens"] == "gen_ai_usage_cache_creation_input_tokens"


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


def test_merge_boundary_uses_canonical_metric_keywords() -> None:
    source = """\
merge_token_usage_into_run(
    run,
    tokens_read=metrics.tokens_read,
    tokens_write=metrics.tokens_write,
    tokens_cache=metrics.tokens_cache,
)
"""

    transformed = transform_source(source, path="src/orchestrator/api/deps.py")

    assert "gen_ai_usage_input_tokens=metrics.gen_ai_usage_input_tokens" in transformed
    assert "gen_ai_usage_output_tokens=metrics.gen_ai_usage_output_tokens" in transformed
    assert (
        "gen_ai_usage_cache_read_input_tokens=metrics.gen_ai_usage_cache_read_input_tokens"
        in transformed
    )
    assert diagnose_source(source, path="src/orchestrator/api/deps.py") == ()


def test_codemod_fixture_literals_are_an_explicit_clean_boundary() -> None:
    source = 'expected = "input_tokens"\n'

    assert diagnose_source(source, path="tests/unit/test_r04_otel_vocab_codemod.py") == ()


def test_task_four_migration_history_is_an_explicit_clean_boundary() -> None:
    source = 'table = sa.Column("tokens_read", sa.Integer())\n'

    assert (
        diagnose_source(
            source,
            path="src/orchestrator/db/migrations/versions/5a37eef8e789_initial_schema.py",
        )
        == ()
    )


def test_task_four_migration_fixture_requires_historical_wrappers() -> None:
    historical_source = """\
def _legacy_usage_snapshot(value):
    return value

historical = _legacy_usage_snapshot({"input_tokens": 1})
"""
    live_source = """\
def _legacy_usage_snapshot(value):
    return value

live = {"input_tokens": 1}
"""

    assert diagnose_source(historical_source, path="tests/integration/test_migrations.py") == ()
    assert diagnose_source(live_source, path="tests/integration/test_migrations.py")


def test_explicit_workflow_event_contract_is_renamed() -> None:
    source = """\
class AttemptUpdated:
    tokens_read: int | None = None

event = AttemptUpdated(tokens_read=1)
total = event.tokens_read
"""

    transformed = transform_source(source, path="src/orchestrator/workflow/events/types.py")

    assert "gen_ai_usage_input_tokens: int | None = None" in transformed
    assert "AttemptUpdated(gen_ai_usage_input_tokens=1)" in transformed
    assert "event.gen_ai_usage_input_tokens" in transformed


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


def test_codex_internal_accumulator_proof_renames_only_internal_counter_keys() -> None:
    source = """\
def extract_turn_usage(payload):
    result = {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0}
    result["tokens_read"] = payload.get("input_tokens", 0)
    return result
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/agents/codex/common.py",
    )

    assert '"gen_ai_usage_input_tokens": 0' in transformed
    assert 'result["gen_ai_usage_input_tokens"]' in transformed
    assert 'payload.get("input_tokens", 0)' in transformed
    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/common.py") == ()


def test_internal_execution_and_workflow_calls_are_proven_by_explicit_callees() -> None:
    source = """\
def _append_attempt_update(tokens_read, tokens_write, tokens_cache):
    return AttemptUpdated(
        tokens_read=tokens_read,
        tokens_write=tokens_write,
        tokens_cache=tokens_cache,
    )

event = _append_attempt_update(
    tokens_read=1,
    tokens_write=2,
    tokens_cache=3,
)
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/execution/attempt_store.py",
    )

    assert "def _append_attempt_update(gen_ai_usage_input_tokens" in transformed
    assert "gen_ai_usage_input_tokens=1" in transformed
    assert "gen_ai_usage_output_tokens=2" in transformed
    assert "gen_ai_usage_cache_read_input_tokens=3" in transformed


def test_explicit_script_report_proof_renames_internal_report_rows_not_sql_literals() -> None:
    source = """\
def run_metrics(run):
    return {"tokens_read": run.get("total_tokens_read", 0)}

def _fetch_aggregates(conn):
    return conn.execute("SELECT input_tokens FROM cost_records")
"""

    transformed = transform_source(source, path="scripts/compare_carriers.py")

    assert '"gen_ai_usage_input_tokens": run.get("total_tokens_read", 0)' in transformed
    assert '"SELECT input_tokens FROM cost_records"' in transformed
    assert diagnose_source(source, path="scripts/compare_carriers.py") == ()


def test_cost_report_allows_only_physical_cost_record_columns() -> None:
    source = """\
METRIC_COLUMNS = ["input_tokens", "output_tokens"]

def _fetch_aggregates(conn):
    return conn.execute("SELECT input_tokens, output_tokens FROM cost_records")

def _format_table(row):
    return {"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"]}
"""

    assert diagnose_source(source, path="scripts/cost_report.py") == ()


def test_cost_report_diagnoses_live_legacy_telemetry_shapes() -> None:
    source = """\
def unrelated(usage):
    attribute = usage.input_tokens
    constructor = AttemptMetrics(input_tokens=1)
    mapping = usage["input_tokens"]
"""

    diagnostics = diagnose_source(source, path="scripts/cost_report.py")

    assert len(diagnostics) == 3
    assert all("input_tokens" in diagnostic for diagnostic in diagnostics)


def test_cost_report_does_not_exempt_non_sql_literals_in_storage_function() -> None:
    source = """\
def _fetch_aggregates():
    return "input_tokens"
"""

    assert diagnose_source(source, path="scripts/cost_report.py")


def test_openhands_provider_cache_attribute_is_an_explicit_raw_boundary() -> None:
    source = """\
def extract_metrics(metrics):
    total_cache = metrics.accumulated_token_usage.cache_read_tokens
    return ExecutionMetrics(tokens_cache=total_cache)
"""

    transformed = transform_source(
        source,
        path="src/orchestrator/runners/agents/openhands/common.py",
    )

    assert "accumulated_token_usage.cache_read_tokens" in transformed
    assert "ExecutionMetrics(gen_ai_usage_cache_read_input_tokens=total_cache)" in transformed
    assert diagnose_source(source, path="src/orchestrator/runners/agents/openhands/common.py") == ()


def test_codemod_legacy_vocabulary_tables_are_an_explicit_self_boundary() -> None:
    source = 'FIELD_RENAMES = {"input_tokens": "gen_ai_usage_input_tokens"}\n'

    assert diagnose_source(source, path="scripts/codemods/r04_otel_vocab.py") == ()


def test_codex_nested_provider_key_candidates_are_a_raw_boundary() -> None:
    source = """\
def extract_token_usage_update(payload):
    def _find_usage(obj):
        return "input_tokens" in obj
    for key in ("inputTokens", "input_tokens"):
        value = payload.get(key)
"""

    assert diagnose_source(source, path="src/orchestrator/runners/agents/codex/common.py") == ()


def test_explicit_test_internal_metric_context_is_mechanically_renamed() -> None:
    source = """\
async def test_attempt_store_appends_events_and_projects_attempt_and_run_totals():
    assert attempt.metrics.tokens_read == 1
"""

    transformed = transform_source(
        source,
        path="tests/integration/test_attempt_store_event_sourcing.py",
    )

    assert "attempt.metrics.gen_ai_usage_input_tokens" in transformed
    assert (
        diagnose_source(source, path="tests/integration/test_attempt_store_event_sourcing.py") == ()
    )


def test_provider_raw_input_fixture_has_a_narrow_test_boundary() -> None:
    source = """\
def _result_event():
    return {"usage": {"input_tokens": 1, "output_tokens": 2}}
"""

    assert diagnose_source(source, path="tests/unit/test_claude_parser.py") == ()


def test_task_four_persisted_event_fixture_has_a_narrow_test_boundary() -> None:
    source = """\
async def test_create_run_replays_initial_attempt_gap_fields():
    payload = {"tokens_read": 1, "tokens_write": 2}
"""

    assert diagnose_source(source, path="tests/unit/test_command_handlers.py") == ()


def test_current_event_assertion_uses_a_proven_internal_payload_receiver() -> None:
    source = """\
def test_attempt_store_appends_events_and_projects_attempt_and_run_totals():
    assert payload.get("tokens_read") == 1
"""

    transformed = transform_source(
        source,
        path="tests/integration/test_attempt_store_event_sourcing.py",
    )

    assert 'payload.get("gen_ai_usage_input_tokens")' in transformed


def test_provider_fixture_preserves_raw_input_but_diagnoses_unwrapped_result_mapping() -> None:
    source = """\
def test_extract_turn_usage_without_usage_field():
    msg = {"usage": {"input_tokens": 1}}
    assert result == {"tokens_read": 1, "tokens_write": 2}
"""

    transformed = transform_source(source, path="tests/unit/test_codex_server_common.py")

    assert '"usage": {"input_tokens": 1}' in transformed
    assert transformed == source
    diagnostics = diagnose_source(source, path="tests/unit/test_codex_server_common.py")
    assert len(diagnostics) == 2


def test_db_source_does_not_exempt_live_legacy_internal_attribute() -> None:
    source = "live = usage.input_tokens\n"

    assert diagnose_source(source, path="src/orchestrator/db/projections/run_state.py")


def test_provider_fixture_does_not_exempt_live_legacy_constructor_keyword() -> None:
    source = "live = ProviderUsage(input_tokens=1)\n"

    assert diagnose_source(source, path="tests/unit/test_codex_server_common.py")


def test_task_four_fixture_does_not_exempt_live_legacy_mapping() -> None:
    source = 'live = {"tokens_read": 1}\n'

    assert diagnose_source(source, path="tests/unit/test_command_handlers.py")


def test_task_four_helper_marks_only_wrapped_historical_mapping() -> None:
    source = """\
def _legacy_usage_snapshot(value):
    return value

def test_snapshot():
    historical = _legacy_usage_snapshot({"input_tokens": 1})
    live = {"input_tokens": 1}
"""

    diagnostics = diagnose_source(source, path="tests/unit/test_command_handlers.py")

    assert len(diagnostics) == 1
    assert "input_tokens" in diagnostics[0]


def test_historical_fixture_wrapper_is_idempotent() -> None:
    source = """\
def _legacy_usage_snapshot(value: object) -> object:
    return value

historical = _legacy_usage_snapshot({"input_tokens": 1})
"""

    assert transform_source(source, path="tests/unit/test_command_handlers.py") == source


def test_projection_legacy_read_fallbacks_are_exact_structural_boundaries() -> None:
    run_state_source = """\
_LEGACY_USAGE_ALIASES = frozenset({"input_tokens"})
def _merge_token_usage_by_model(previous, usage):
    return previous.get("input_tokens", 0) + usage.get("input_tokens", 0)
"""
    task_state_source = """\
def _attempt_values_from_snapshot(metrics):
    return {"tokens_read": metrics.get("tokens_read", 0)}
"""
    live_source = 'live = usage.get("input_tokens", 0)\n'

    assert (
        diagnose_source(run_state_source, path="src/orchestrator/db/projections/run_state.py") == ()
    )
    assert (
        diagnose_source(task_state_source, path="src/orchestrator/db/projections/task_state.py")
        == ()
    )
    assert diagnose_source(live_source, path="src/orchestrator/db/projections/run_state.py")


def test_physical_orm_usage_is_limited_to_exact_storage_functions() -> None:
    storage_source = """\
async def update_latest_attempt():
    attempt.tokens_read = attempt.tokens_read + 1
"""
    live_source = """\
async def unrelated():
    attempt.tokens_read = attempt.tokens_read + 1
"""

    assert diagnose_source(storage_source, path="src/orchestrator/db/access/mutations.py") == ()
    assert diagnose_source(live_source, path="src/orchestrator/db/access/mutations.py")


def test_projection_alias_canonicalizer_is_an_exact_literal_boundary() -> None:
    canonicalizer_source = """\
def _canonicalize_usage_entry(entry):
    return entry.get("input_tokens", 0)
"""
    live_source = """\
def unrelated(entry):
    return entry.get("input_tokens", 0)
"""

    assert (
        diagnose_source(canonicalizer_source, path="src/orchestrator/db/projections/run_state.py")
        == ()
    )
    assert diagnose_source(live_source, path="src/orchestrator/db/projections/run_state.py")


def test_provider_fixture_call_preserves_only_raw_provider_builder_arguments() -> None:
    raw_source = """\
def test_result_event():
    event = _result_event("done", input_tokens=1, output_tokens=2)
"""
    live_source = """\
def test_result_event():
    event = ProviderUsage(input_tokens=1)
"""

    assert diagnose_source(raw_source, path="tests/unit/test_claude_parser.py") == ()
    assert diagnose_source(live_source, path="tests/unit/test_claude_parser.py")


def test_historical_orm_assertion_is_limited_to_reviewed_fixture_function() -> None:
    historical_source = """\
async def test_create_run_replays_initial_attempt_gap_fields():
    assert attempt.tokens_read == 2
"""
    live_source = """\
async def test_new_live_assertion():
    assert attempt.tokens_read == 2
"""

    assert diagnose_source(historical_source, path="tests/unit/test_command_handlers.py") == ()
    assert diagnose_source(live_source, path="tests/unit/test_command_handlers.py")
    assert (
        transform_source(historical_source, path="tests/unit/test_command_handlers.py")
        == historical_source
    )


def test_historical_fixture_attributes_require_the_exact_orm_allowlist() -> None:
    sources = {
        "tests/unit/test_command_handlers.py": """\
def test_unreviewed_fixture():
    assert attempt.tokens_read == 2
""",
        "tests/integration/test_database.py": """\
def test_unreviewed_fixture():
    assert attempt.tokens_read == 2
""",
    }

    for path, source in sources.items():
        diagnostics = diagnose_source(source, path=path)

        assert len(diagnostics) == 1
        assert "tokens_read" in diagnostics[0]


def test_unwrapped_historical_comparison_dictionary_is_diagnostic() -> None:
    source = 'assert result == {"input_tokens": 1}\n'

    diagnostics = diagnose_source(source, path="tests/unit/test_command_handlers.py")

    assert len(diagnostics) == 1
    assert "input_tokens" in diagnostics[0]


def test_explicitly_wrapped_historical_comparison_dictionary_is_allowed() -> None:
    source = """\
def _legacy_usage_snapshot(value):
    return value

assert result == _legacy_usage_snapshot({"input_tokens": 1})
"""

    assert diagnose_source(source, path="tests/unit/test_command_handlers.py") == ()


def test_provider_fake_attribute_is_limited_to_reviewed_fixture_function() -> None:
    raw_source = """\
def test_extract_metrics_multiple_models():
    return usage.cache_read_tokens
"""
    live_source = """\
def test_live_metric():
    return usage.cache_read_tokens
"""

    assert diagnose_source(raw_source, path="tests/unit/test_openhands_common.py") == ()
    assert diagnose_source(live_source, path="tests/unit/test_openhands_common.py")


def test_codex_fixture_preserves_total_token_usage_provider_shape_only() -> None:
    raw_source = """\
def test_extract_token_usage_update_camel_and_snake():
    message = {"total_token_usage": {"input_tokens": 1, "output_tokens": 2}}
"""
    live_source = """\
def test_unrelated_mapping():
    message = {"input_tokens": 1, "output_tokens": 2}
"""

    assert diagnose_source(raw_source, path="tests/unit/test_codex_server_common.py") == ()
    assert diagnose_source(live_source, path="tests/unit/test_codex_server_common.py")


def test_current_event_payload_fixture_is_mechanically_canonicalized() -> None:
    source = """\
async def test_gatekeeper_cost_fields_survive_summary_reconstruction():
    payload = {"cache_write_tokens": 3}
"""

    transformed = transform_source(
        source, path="tests/unit/test_file_state_gatekeeper_event_payloads.py"
    )

    assert '"gen_ai_usage_cache_creation_input_tokens": 3' in transformed
    assert (
        diagnose_source(source, path="tests/unit/test_file_state_gatekeeper_event_payloads.py")
        == ()
    )


def test_historical_fixture_helper_marks_only_wrapped_mapping_access() -> None:
    source = """\
def _legacy_usage_snapshot(value):
    return value

historical = _legacy_usage_snapshot(snapshot)["input_tokens"]
live = snapshot["input_tokens"]
"""

    diagnostics = diagnose_source(source, path="tests/unit/test_run_aggregation.py")

    assert len(diagnostics) == 1
    assert "input_tokens" in diagnostics[0]


def test_unwrapped_historical_fixture_dictionary_is_diagnostic() -> None:
    source = '''\
"""Fixture module."""
from __future__ import annotations

historical = {"input_tokens": 1}
'''

    assert diagnose_source(source, path="tests/unit/test_run_aggregation.py")
