"""Tests for prompt generation."""

from orchestrator.agents.claude_sdk import build_claude_sdk_prompt
from orchestrator.agents.codex_server_common import build_codex_server_prompt
from orchestrator.agents.openhands_common import build_openhands_prompt
from orchestrator.agents.cli import CLIAgent
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.models import (
    RequirementConfig,
    RubricItemConfig,
    SubmissionTemplateConfig,
    TaskConfig,
    VerifierConfig,
)
from orchestrator.state.models import Attempt, TaskState
from orchestrator.workflow.prompts import (
    generate_builder_prompt,
    generate_verifier_prompt,
    get_task_context,
)


def _task_config(
    task_context: str = "Implement {{feature}}",
    model_overrides: dict[str, dict[str, str]] | None = None,
    rubric: list[RubricItemConfig] | None = None,
) -> TaskConfig:
    verifier = VerifierConfig()
    if rubric:
        verifier = VerifierConfig(rubric=rubric)
    return TaskConfig(
        id="T-01",
        title="Test Task",
        task_context=task_context,
        model_overrides=model_overrides,
        requirements=[
            RequirementConfig(id="R1", desc="Create the feature"),
            RequirementConfig(id="R2", desc="Add tests"),
        ],
        verifier=verifier,
    )


def _task_state(verifier_comment: str | None = None) -> TaskState:
    state = TaskState(id="task-1", config_id="T-01")
    if verifier_comment:
        state.attempts.append(Attempt(attempt_num=1, verifier_comment=verifier_comment))
    return state


# --- get_task_context ---


def test_get_task_context_default() -> None:
    config = _task_config(task_context="Default context")
    assert get_task_context(config) == "Default context"


def test_get_task_context_no_model() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model=None) == "Default context"


def test_get_task_context_model_override_applied() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model="claude") == "Claude context"


def test_get_task_context_model_not_in_overrides() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude context"}},
    )
    assert get_task_context(config, model="gpt4") == "Default context"


# --- generate_builder_prompt ---


def test_builder_prompt_basic() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert "auth" in prompt.task_context  # Variable substituted
    assert "{{feature}}" not in prompt.task_context
    assert len(prompt.requirements) == 2
    assert "Create the feature" in prompt.requirements[0]
    assert "software developer" in prompt.system.lower()
    assert "builder phase" in prompt.system.lower()
    assert prompt.previous_feedback is None


def test_builder_prompt_variable_substitution() -> None:
    config = _task_config(task_context="Build {{name}} for {{team}}")
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"name": "widget", "team": "platform"})

    assert "widget" in prompt.task_context
    assert "platform" in prompt.task_context
    assert "{{name}}" not in prompt.task_context


def test_builder_prompt_model_override() -> None:
    config = _task_config(
        task_context="Default context",
        model_overrides={"claude": {"task_context": "Claude-specific for {{feature}}"}},
    )
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"}, model="claude")

    assert "Claude-specific for auth" in prompt.task_context


def test_builder_prompt_previous_feedback() -> None:
    config = _task_config()
    state = _task_state(verifier_comment="Fix the error handling")
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.previous_feedback == "Fix the error handling"
    assert "Previous Feedback" in prompt.user
    assert "Fix the error handling" in prompt.user


def test_builder_prompt_no_feedback_on_first_attempt() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.previous_feedback is None
    assert "Previous Feedback" not in prompt.user


# --- generate_verifier_prompt ---


def test_verifier_prompt_basic() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.requirements) == 2
    assert "code reviewer" in prompt.system.lower()
    assert "verifier phase" in prompt.system.lower()
    assert "Grade each requirement" in prompt.submission_instructions


def test_verifier_prompt_with_rubric() -> None:
    config = _task_config(
        rubric=[
            RubricItemConfig(id="Q1", text="Is the code well-structured?"),
            RubricItemConfig(id="Q2", text="Are edge cases handled?"),
        ],
    )
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.rubric) == 2
    assert "well-structured" in prompt.rubric[0]
    assert "Rubric Questions" in prompt.user


def test_verifier_prompt_empty_rubric() -> None:
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert len(prompt.rubric) == 0
    assert "Evaluate based on requirements only" in prompt.user


def test_verifier_prompt_submission_instructions() -> None:
    config = TaskConfig(
        id="T-01",
        title="Test",
        task_context="Context",
        requirements=[RequirementConfig(id="R1", desc="Test")],
        verifier=VerifierConfig(
            submission_template=SubmissionTemplateConfig(
                grade_scale=["A", "B", "C"],
                require_reason_if_below="A",
                require_remediation_if_below="B",
            ),
        ),
    )
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert "A, B, C" in prompt.submission_instructions
    assert "reason if grade below A" in prompt.submission_instructions
    assert "remediation if grade below B" in prompt.submission_instructions


# --- step_context in builder prompt ---


def test_builder_prompt_without_step_context_unchanged() -> None:
    """Prompt without step_context should not include Step Context section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.step_context is None
    assert "## Step Context" not in prompt.user
    # Prompt should start with ## Task
    assert prompt.user.startswith("## Task\n")


def test_builder_prompt_with_step_context() -> None:
    """Prompt with step_context should include Step Context section before task."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config, state, {"feature": "auth"}, step_context="This step sets up the backend."
    )

    assert prompt.step_context == "This step sets up the backend."
    assert "## Step Context\nThis step sets up the backend." in prompt.user
    # Step Context should appear before Task
    step_ctx_pos = prompt.user.index("## Step Context")
    task_pos = prompt.user.index("## Task")
    assert step_ctx_pos < task_pos


def test_builder_prompt_step_context_variable_substitution() -> None:
    """Variable substitution should work in step_context the same as task_context."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth", "team": "platform"},
        step_context="Setting up {{feature}} for {{team}}.",
    )

    assert prompt.step_context == "Setting up auth for platform."
    assert "{{feature}}" not in prompt.step_context
    assert "{{team}}" not in prompt.step_context
    assert "Setting up auth for platform." in prompt.user


def test_builder_prompt_step_context_with_previous_feedback() -> None:
    """Step context and previous feedback should both appear in the prompt."""
    config = _task_config()
    state = _task_state(verifier_comment="Fix error handling")
    prompt = generate_builder_prompt(
        config, state, {"feature": "auth"}, step_context="Backend setup step."
    )

    assert "## Step Context" in prompt.user
    assert "## Previous Feedback" in prompt.user
    # Order: Step Context, Task, Requirements, Previous Feedback
    step_ctx_pos = prompt.user.index("## Step Context")
    task_pos = prompt.user.index("## Task")
    feedback_pos = prompt.user.index("## Previous Feedback")
    assert step_ctx_pos < task_pos < feedback_pos


# --- step_context in verifier prompt ---


def test_verifier_prompt_without_step_context_unchanged() -> None:
    """Verifier prompt without step_context should not include Step Context section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert prompt.step_context is None
    assert "## Step Context" not in prompt.user
    # Prompt should start with ## Requirements to Verify
    assert prompt.user.startswith("## Requirements to Verify")


def test_verifier_prompt_with_step_context() -> None:
    """Verifier prompt with step_context should include Step Context section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state, step_context="This step sets up the backend.")

    assert prompt.step_context == "This step sets up the backend."
    assert "## Step Context\nThis step sets up the backend." in prompt.user
    # Step Context should appear before Requirements to Verify
    step_ctx_pos = prompt.user.index("## Step Context")
    req_pos = prompt.user.index("## Requirements to Verify")
    assert step_ctx_pos < req_pos


def test_verifier_prompt_step_context_is_not_substituted() -> None:
    """Verifier prompt does not do variable substitution on step_context.

    Variable substitution is a builder-only feature (builder has config dict,
    verifier does not). The step_context is passed through as-is.
    """
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(
        config, state, step_context="Review the {{feature}} implementation."
    )

    # Verifier does not do variable substitution, so {{feature}} remains as-is
    assert prompt.step_context == "Review the {{feature}} implementation."
    assert "Review the {{feature}} implementation." in prompt.user


# --- clarifications_path in builder prompt ---


def test_builder_prompt_without_clarifications_path_unchanged() -> None:
    """Prompt without clarifications_path should not include Clarifications section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})

    assert prompt.clarifications_path is None
    assert "## Clarifications" not in prompt.user


def test_builder_prompt_with_clarifications_path() -> None:
    """Prompt with clarifications_path should include Clarifications section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config, state, {"feature": "auth"}, clarifications_path="/tmp/clarifications.md"
    )

    assert prompt.clarifications_path == "/tmp/clarifications.md"
    assert "## Clarifications" in prompt.user
    assert "/tmp/clarifications.md" in prompt.user
    assert "Previous clarifications from the human are recorded in:" in prompt.user
    assert "Review this file for context on decisions made." in prompt.user
    assert "use the request_clarification tool" in prompt.user


def test_builder_prompt_clarifications_path_positioned_after_step_context() -> None:
    """Clarifications section should appear after Step Context but before Task."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        step_context="Backend setup step.",
        clarifications_path="/tmp/clarifications.md",
    )

    step_ctx_pos = prompt.user.index("## Step Context")
    clarifications_pos = prompt.user.index("## Clarifications")
    task_pos = prompt.user.index("## Task")
    assert step_ctx_pos < clarifications_pos < task_pos


def test_builder_prompt_clarifications_path_without_step_context() -> None:
    """Clarifications section should appear before Task when no Step Context."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config, state, {"feature": "auth"}, clarifications_path="/tmp/clarifications.md"
    )

    clarifications_pos = prompt.user.index("## Clarifications")
    task_pos = prompt.user.index("## Task")
    assert clarifications_pos < task_pos
    # Should start with Step Context or Clarifications
    assert (
        prompt.user.startswith("## Clarifications") or prompt.user.startswith("## Step Context")
    ) or "## Step Context" not in prompt.user


def test_builder_prompt_clarifications_with_all_sections() -> None:
    """All sections should appear in correct order: Step Context, Clarifications, Task, Requirements, Previous Feedback."""
    config = _task_config()
    state = _task_state(verifier_comment="Fix error handling")
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        step_context="Backend setup.",
        clarifications_path="/tmp/clarifications.md",
    )

    step_ctx_pos = prompt.user.index("## Step Context")
    clarifications_pos = prompt.user.index("## Clarifications")
    task_pos = prompt.user.index("## Task")
    req_pos = prompt.user.index("## Requirements")
    feedback_pos = prompt.user.index("## Previous Feedback")

    assert step_ctx_pos < clarifications_pos < task_pos < req_pos < feedback_pos


# --- clarifications_path in verifier prompt ---


def test_verifier_prompt_without_clarifications_path_unchanged() -> None:
    """Prompt without clarifications_path should not include Clarifications section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state)

    assert prompt.clarifications_path is None
    assert "## Clarifications" not in prompt.user


def test_verifier_prompt_with_clarifications_path() -> None:
    """Prompt with clarifications_path should include Clarifications section."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state, clarifications_path="/tmp/clarifications.md")

    assert prompt.clarifications_path == "/tmp/clarifications.md"
    assert "## Clarifications" in prompt.user
    assert "/tmp/clarifications.md" in prompt.user
    assert "Previous clarifications from the human are recorded in:" in prompt.user
    assert "Review this file for context on decisions made." in prompt.user
    assert "use the request_clarification tool" in prompt.user


def test_verifier_prompt_clarifications_path_positioned_after_step_context() -> None:
    """Clarifications section should appear after Step Context but before Requirements."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(
        config,
        state,
        step_context="Backend review step.",
        clarifications_path="/tmp/clarifications.md",
    )

    step_ctx_pos = prompt.user.index("## Step Context")
    clarifications_pos = prompt.user.index("## Clarifications")
    req_pos = prompt.user.index("## Requirements to Verify")
    assert step_ctx_pos < clarifications_pos < req_pos


def test_verifier_prompt_clarifications_path_without_step_context() -> None:
    """Clarifications section should appear before Requirements when no Step Context."""
    config = _task_config()
    state = _task_state()
    prompt = generate_verifier_prompt(config, state, clarifications_path="/tmp/clarifications.md")

    clarifications_pos = prompt.user.index("## Clarifications")
    req_pos = prompt.user.index("## Requirements to Verify")
    assert clarifications_pos < req_pos


# --- clarification_line_range in builder prompt ---


def test_builder_prompt_with_clarification_line_range() -> None:
    """Prompt with clarification_line_range should include file path and line range."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarifications_path="/artifact.md",
        clarification_line_range=("/artifact.md", 5, 12),
    )

    assert "lines 5\u201312" in prompt.user
    assert "/artifact.md" in prompt.user
    assert prompt.clarification_line_range == ("/artifact.md", 5, 12)


def test_builder_prompt_line_range_requires_clarifications_path() -> None:
    """clarification_line_range without clarifications_path does not add line-range text."""
    config = _task_config()
    state = _task_state()
    # Without clarifications_path, the clarification block is not emitted at all
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarification_line_range=("/artifact.md", 5, 12),
    )

    assert "lines 5\u201312" not in prompt.user
    assert "## Clarifications" not in prompt.user


def test_builder_prompt_line_range_no_regression() -> None:
    """Without new params, output matches baseline (no regression)."""
    config = _task_config()
    state = _task_state()
    baseline_prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
    )
    explicit_none_prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarification_line_range=None,
        skipped_questions=None,
        skip_reason=None,
    )

    assert explicit_none_prompt == baseline_prompt


# --- skipped_questions / skip_reason in builder prompt ---


def test_builder_prompt_with_skipped_questions() -> None:
    """Prompt with skipped_questions should include declined-to-answer message with reason."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarifications_path="/artifact.md",
        skipped_questions=["Question 1"],
        skip_reason="Too vague",
    )

    assert "declined to answer" in prompt.user
    assert "Too vague" in prompt.user
    assert prompt.skipped_questions == ["Question 1"]


def test_builder_prompt_skip_without_reason() -> None:
    """skipped_questions without skip_reason uses 'none given' fallback."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarifications_path="/artifact.md",
        skipped_questions=["Q1", "Q2"],
    )

    assert "declined to answer" in prompt.user
    assert "none given" in prompt.user
    assert '"Q1"' in prompt.user
    assert '"Q2"' in prompt.user


def test_builder_prompt_skip_requires_clarifications_path() -> None:
    """skipped_questions without clarifications_path does not add skip text."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        skipped_questions=["Question 1"],
        skip_reason="Too vague",
    )

    assert "declined to answer" not in prompt.user
    assert "## Clarifications" not in prompt.user


def test_builder_prompt_line_range_and_skip_combined() -> None:
    """Both clarification_line_range and skipped_questions appear together."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(
        config,
        state,
        {"feature": "auth"},
        clarifications_path="/artifact.md",
        clarification_line_range=("/artifact.md", 5, 12),
        skipped_questions=["Question 1"],
        skip_reason="Too vague",
    )

    assert "lines 5\u201312" in prompt.user
    assert "/artifact.md" in prompt.user
    assert "declined to answer" in prompt.user
    assert "Too vague" in prompt.user


# --- D4 dead-weight removal ---


def _shared_system_prompt() -> str:
    """Return the system section of a generated builder prompt."""
    config = _task_config()
    state = _task_state()
    return generate_builder_prompt(config, state, {"feature": "auth"}).system


def _make_context(prompt: str) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt=prompt,
        requirements=["R1: do the thing"],
    )


def test_avoiding_loops_removed_from_shared_prompt() -> None:
    """'Avoiding Loops' section must not appear in the shared builder system prompt."""
    system = _shared_system_prompt()
    assert "Avoiding Loops" not in system


def test_required_sections_still_in_shared_prompt() -> None:
    """Required task context, requirements, and workflow sections remain in shared prompt."""
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})
    # Task context and requirements are in the user section
    assert "## Task" in prompt.user
    assert "## Requirements" in prompt.user
    # Workflow and callback instructions remain
    assert "BUILDER phase" in prompt.system
    assert "submit" in prompt.system.lower()


def test_git_commit_instructions_not_in_shared_prompt() -> None:
    """Git commit instructions must NOT appear in the shared builder system prompt.

    They have been moved to each agent's individual prompt builder.
    """
    config = _task_config()
    state = _task_state()
    prompt = generate_builder_prompt(config, state, {"feature": "auth"})
    assert "git add" not in prompt.system
    assert "git commit" not in prompt.system


def test_git_commit_instructions_in_cli_agent_prompt() -> None:
    """CLIAgent.build_prompt explicitly adds git commit instructions for builder phase."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    # Without api_base_url, build_prompt adds git workflow section for builder phase
    result = CLIAgent.build_prompt(shared_prompt, context)
    assert "git add" in result
    assert "git commit" in result


def test_git_commit_instructions_in_claude_sdk_prompt() -> None:
    """build_claude_sdk_prompt explicitly adds git commit instructions."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = build_claude_sdk_prompt(context, is_verifier=False)
    assert "git add" in result
    assert "git commit" in result


def test_git_commit_instructions_in_codex_server_prompt() -> None:
    """build_codex_server_prompt explicitly adds git commit instructions."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = build_codex_server_prompt(context, is_verifier=False)
    assert "git add" in result
    assert "git commit" in result


def test_git_commit_instructions_in_openhands_prompt() -> None:
    """build_openhands_prompt explicitly adds git commit instructions."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = build_openhands_prompt(context, is_verifier=False)
    assert "git add" in result
    assert "git commit" in result


def test_avoiding_loops_removed_from_openhands_builder_prompt() -> None:
    """'Avoiding Loops' section must not appear in the openhands builder prompt."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = build_openhands_prompt(context, is_verifier=False)
    assert "Avoiding Loops" not in result


def test_avoiding_loops_removed_from_openhands_verifier_prompt() -> None:
    """'Avoiding Loops' section must not appear in the openhands verifier prompt."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = build_openhands_prompt(context, is_verifier=True)
    assert "Avoiding Loops" not in result


# --- Agent-specific behavioral instructions ---


def test_cli_agent_includes_git_workflow_section() -> None:
    """CLIAgent.build_prompt includes a dedicated Git Workflow section."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    result = CLIAgent.build_prompt(shared_prompt, context)
    assert "## Git Workflow" in result
    assert "git --no-pager" in result
    assert "Commit conventions" in result


def test_cli_agent_no_git_section_for_verifier() -> None:
    """CLIAgent.build_prompt does NOT add git workflow for verifier phase."""
    shared_prompt = _shared_system_prompt()
    context = _make_context(shared_prompt)
    # api_base_url=None, verifying phase — returns prompt unchanged (no git section)
    result = CLIAgent.build_prompt(shared_prompt, context, phase="verifying")
    assert "## Git Workflow" not in result


def test_openhands_prompt_includes_file_rereading_avoidance() -> None:
    """build_openhands_prompt includes file re-reading avoidance instructions."""
    context = _make_context("Some prompt")
    result = build_openhands_prompt(context, is_verifier=False)
    assert "re-read" in result.lower() or "NEVER re-read" in result
    assert "File Exploration Guidelines" in result


def test_openhands_prompt_includes_docker_awareness() -> None:
    """build_openhands_prompt includes Docker/container awareness instructions."""
    context = _make_context("Some prompt")
    result = build_openhands_prompt(context, is_verifier=False)
    assert "Container Awareness" in result or "Docker" in result


def test_openhands_prompt_includes_git_workflow() -> None:
    """build_openhands_prompt includes a Git Workflow section."""
    context = _make_context("Some prompt")
    result = build_openhands_prompt(context, is_verifier=False)
    assert "## Git Workflow" in result


def test_codex_prompt_includes_sandbox_constraints() -> None:
    """build_codex_server_prompt includes sandbox constraint instructions."""
    context = _make_context("Some prompt")
    result = build_codex_server_prompt(context, is_verifier=False)
    assert "Sandbox Constraints" in result
    assert "network" in result.lower()


def test_codex_prompt_includes_response_style() -> None:
    """build_codex_server_prompt includes response style guidance."""
    context = _make_context("Some prompt")
    result = build_codex_server_prompt(context, is_verifier=False)
    assert "Response Style" in result
    assert "concise" in result.lower()


def test_codex_prompt_includes_git_workflow() -> None:
    """build_codex_server_prompt includes a Git Workflow section."""
    context = _make_context("Some prompt")
    result = build_codex_server_prompt(context, is_verifier=False)
    assert "## Git Workflow" in result


def test_claude_sdk_prompt_includes_tool_usage_patterns() -> None:
    """build_claude_sdk_prompt includes tool usage pattern instructions."""
    context = _make_context("Some prompt")
    result = build_claude_sdk_prompt(context, is_verifier=False)
    assert "Tool Usage Patterns" in result
    assert "update_checklist" in result


def test_claude_sdk_prompt_includes_sub_agent_guidance() -> None:
    """build_claude_sdk_prompt includes sub-agent guidance instructions."""
    context = _make_context("Some prompt")
    result = build_claude_sdk_prompt(context, is_verifier=False)
    assert "Sub-Agent Guidance" in result


def test_claude_sdk_prompt_includes_git_workflow() -> None:
    """build_claude_sdk_prompt includes a Git Workflow section."""
    context = _make_context("Some prompt")
    result = build_claude_sdk_prompt(context, is_verifier=False)
    assert "## Git Workflow" in result


def test_agent_specific_sections_not_in_verifier_prompts() -> None:
    """Agent-specific builder sections should not appear in verifier prompts."""
    context = _make_context("Some prompt")
    # Codex verifier prompt should not have sandbox constraints or response style
    codex_verifier = build_codex_server_prompt(context, is_verifier=True)
    assert "Sandbox Constraints" not in codex_verifier
    assert "Response Style" not in codex_verifier
    # OpenHands verifier should not have file re-reading avoidance
    oh_verifier = build_openhands_prompt(context, is_verifier=True)
    assert "File Exploration Guidelines" not in oh_verifier
    # Claude SDK verifier should not have sub-agent guidance
    sdk_verifier = build_claude_sdk_prompt(context, is_verifier=True)
    assert "Sub-Agent Guidance" not in sdk_verifier
