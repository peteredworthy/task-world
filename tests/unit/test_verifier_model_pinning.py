"""Unit tests for verifier model pinning.

Verifies that:
- Run.verifier_model defaults correctly
- resolve_verifier_config() applies the pinned model override
- Changing agent_config after creation doesn't affect the resolved config
"""

from __future__ import annotations

from orchestrator.runners.executor import resolve_verifier_config
from orchestrator.state.models import Run


# ---------------------------------------------------------------------------
# Unit tests: Run state model
# ---------------------------------------------------------------------------


def test_run_verifier_model_defaults_to_none() -> None:
    """Run.verifier_model defaults to None for backwards compatibility."""
    run = Run(id="r1", repo_name="repo")
    assert run.verifier_model is None


def test_run_verifier_model_can_be_set() -> None:
    """Run.verifier_model can be set to a model string."""
    run = Run(id="r1", repo_name="repo", verifier_model="claude-opus-4-5")
    assert run.verifier_model == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# Unit tests: resolve_verifier_config (pure function)
# ---------------------------------------------------------------------------


def test_pinned_model_overrides_agent_config() -> None:
    """When verifier_model is set, it overrides agent_config['model']."""
    config = resolve_verifier_config(
        agent_config={"model": "claude-sonnet-4-5", "max_turns": 50},
        verifier_model="claude-opus-4-5",
    )
    assert config["model"] == "claude-opus-4-5"
    assert config["max_turns"] == 50


def test_no_pinned_model_preserves_agent_config() -> None:
    """When verifier_model is None, agent_config is returned unchanged."""
    config = resolve_verifier_config(
        agent_config={"model": "claude-sonnet-4-5"},
        verifier_model=None,
    )
    assert config["model"] == "claude-sonnet-4-5"


def test_pinned_model_adds_model_key_when_absent() -> None:
    """When agent_config has no model key, pinned model is added."""
    config = resolve_verifier_config(
        agent_config={"max_turns": 30},
        verifier_model="claude-opus-4-5",
    )
    assert config["model"] == "claude-opus-4-5"
    assert config["max_turns"] == 30


def test_no_pinned_model_and_no_model_key() -> None:
    """When neither pinned nor agent_config has model, result has no model key."""
    config = resolve_verifier_config(
        agent_config={"max_turns": 30},
        verifier_model=None,
    )
    assert "model" not in config


def test_resolve_does_not_mutate_original() -> None:
    """resolve_verifier_config returns a copy; original is not mutated."""
    original = {"model": "claude-sonnet-4-5"}
    config = resolve_verifier_config(original, verifier_model="claude-opus-4-5")
    assert config["model"] == "claude-opus-4-5"
    assert original["model"] == "claude-sonnet-4-5"


def test_changing_agent_config_after_creation_does_not_affect_pinned() -> None:
    """Simulates post-creation config change: pinned model wins regardless."""
    run = Run(
        id="r1",
        repo_name="repo",
        agent_config={"model": "claude-sonnet-4-5"},
        verifier_model="claude-opus-4-5",
    )

    # Simulate post-creation mutation
    run.agent_config = {"model": "claude-haiku-4-5"}

    config = resolve_verifier_config(run.agent_config, run.verifier_model)
    assert config["model"] == "claude-opus-4-5"
