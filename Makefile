# Orchestrator project Makefile
# Provides named test targets for explicit CI/CD invocation.
# All targets use: uv run pytest

.PHONY: test \
        test-codex \
        test-codex-unit \
        test-codex-integration \
        test-codex-detector \
        test-codex-local \
        test-codex-remote \
        test-codex-errors \
        test-codex-executor \
        test-codex-api \
        test-codex-callbacks \
        test-codex-allowlist \
        test-codex-parity \
        check-enum-drift


# ---------------------------------------------------------------------------
# Full suite
# ---------------------------------------------------------------------------

test:
	uv run pytest


# ---------------------------------------------------------------------------
# All Codex-specific targets (unit + integration)
# ---------------------------------------------------------------------------

test-codex: test-codex-unit test-codex-integration


# ---------------------------------------------------------------------------
# Codex unit targets — explicit file list
# ---------------------------------------------------------------------------

# Runs every Codex-specific unit test file.
test-codex-unit:
	uv run pytest \
		tests/unit/test_tool_detector.py \
		tests/unit/test_codex_server_agent.py \
		tests/unit/test_codex_server_remote.py \
		tests/unit/test_codex_server_common.py \
		tests/unit/test_codex_server_callbacks.py \
		tests/unit/test_codex_server_parity.py \
		tests/unit/test_executor_codex.py \
		tests/unit/test_executor_codex_lifecycle.py \
		-v


# ---------------------------------------------------------------------------
# Codex integration targets — explicit file list
# ---------------------------------------------------------------------------

# Runs every Codex-specific integration test file.
test-codex-integration:
	uv run pytest \
		tests/integration/test_codex_lifecycle.py \
		tests/integration/test_codex_server_remote_parity.py \
		tests/integration/test_api_runs_codex_agent_types.py \
		-v


# ---------------------------------------------------------------------------
# Focused targets by coverage area
# ---------------------------------------------------------------------------

# Detector metadata: agent presence, config schema fields, titles, descriptions,
# availability flags, install hints, and model field presence for both variants.
test-codex-detector:
	uv run pytest tests/unit/test_tool_detector.py -k "codex" -v

# Local agent: protocol surface (info/execute/cancel), phase-aware prompt
# assembly, allow-list enforcement, cancel idempotency, error type mapping.
test-codex-local:
	uv run pytest \
		tests/unit/test_codex_server_agent.py \
		tests/unit/test_codex_server_common.py \
		-v

# Remote agent: config validation, token resolution, bearer auth security,
# agent protocol, allow-list enforcement, cancel/error mapping.
test-codex-remote:
	uv run pytest tests/unit/test_codex_server_remote.py -v

# Error mapping: transport exceptions → typed AgentExecutionError /
# AgentNotAvailableError / AgentTimeoutError / AgentCancelledError.
# Covers both local and remote failure paths.
test-codex-errors:
	uv run pytest \
		tests/unit/test_codex_server_agent.py \
		tests/unit/test_codex_server_remote.py \
		-k "error or fail or timeout or connect or http or cancel or secret or leak" \
		-v

# Executor dispatch: _create_agent instantiates correct class for CODEX_SERVER
# and CODEX_SERVER_REMOTE; config values are forwarded; lifecycle (spawn,
# pause, resume, cancel, health monitoring) is correct.
test-codex-executor:
	uv run pytest \
		tests/unit/test_executor_codex.py \
		tests/unit/test_executor_codex_lifecycle.py \
		-v

# API exposure: codex_server and codex_server_remote agent types are accepted
# by the runs REST API (POST /api/runs, GET /api/runs/{id}, POST /api/runs/{id}/resume).
test-codex-api:
	uv run pytest tests/integration/test_api_runs_codex_agent_types.py -v

# Callback parity: all four cells of the builder/verifier × REST/MCP matrix
# are covered for both the local and remote agent variants.
test-codex-callbacks:
	uv run pytest \
		tests/unit/test_codex_server_callbacks.py \
		tests/unit/test_codex_server_parity.py \
		tests/integration/test_codex_server_remote_parity.py \
		-v

# Allow-listed tool enforcement: only the four v1 tools are accepted;
# any other tool call raises ValueError before any callback is invoked.
test-codex-allowlist:
	uv run pytest \
		tests/unit/test_codex_server_common.py \
		tests/unit/test_codex_server_agent.py \
		tests/unit/test_codex_server_remote.py \
		tests/unit/test_codex_server_parity.py \
		-k "allow or disallow or allowlist or disallowed or reject" \
		-v

# Prompt and callback parity between local and remote variants across all
# four matrix cells (builder/verifier × REST/MCP).
test-codex-parity:
	uv run pytest \
		tests/unit/test_codex_server_parity.py \
		tests/integration/test_codex_server_remote_parity.py \
		-v


# ---------------------------------------------------------------------------
# Enum codegen drift check
# ---------------------------------------------------------------------------

check-enum-drift:
	uv run python scripts/export_enums.py --check
