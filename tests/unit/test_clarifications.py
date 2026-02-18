"""Unit tests for clarification models and pure functions."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.workflow.clarifications import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationRequest,
    ClarificationResponse,
    build_artifact_header,
    format_clarification_artifact,
    resolve_artifact_path,
)


def test_clarification_question_model():
    """Test ClarificationQuestion model validation."""
    q = ClarificationQuestion(
        id="q1",
        question="What color?",
        context="Need to choose a theme color",
        options=["Red", "Blue", "Green"],
    )
    assert q.id == "q1"
    assert q.question == "What color?"
    assert len(q.options) == 3


def test_clarification_answer_model():
    """Test ClarificationAnswer model with selected option."""
    now = datetime.now(timezone.utc)
    a = ClarificationAnswer(
        question_id="q1",
        selected_option="Blue",
        answered_by="alice",
        answered_at=now,
    )
    assert a.question_id == "q1"
    assert a.selected_option == "Blue"
    assert a.free_text is None


def test_clarification_answer_with_free_text():
    """Test ClarificationAnswer model with free text."""
    now = datetime.now(timezone.utc)
    a = ClarificationAnswer(
        question_id="q1",
        free_text="Custom answer here",
        answered_by="alice",
        answered_at=now,
    )
    assert a.free_text == "Custom answer here"
    assert a.selected_option is None


def test_clarification_request_model():
    """Test ClarificationRequest model."""
    now = datetime.now(timezone.utc)
    q1 = ClarificationQuestion(id="q1", question="Q1?", context="Context1", options=["A", "B"])
    q2 = ClarificationQuestion(id="q2", question="Q2?", context="Context2", options=["X", "Y", "Z"])

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=1,
        questions=[q1, q2],
        created_at=now,
    )
    assert req.id == "req1"
    assert len(req.questions) == 2
    assert req.responded_at is None


def test_clarification_response_model():
    """Test ClarificationResponse model."""
    now = datetime.now(timezone.utc)
    a1 = ClarificationAnswer(
        question_id="q1",
        selected_option="A",
        answered_by="bob",
        answered_at=now,
    )
    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1],
        responded_at=now,
    )
    assert resp.request_id == "req1"
    assert len(resp.answers) == 1


def test_format_clarification_artifact_with_selected_options():
    """Test formatting with selected options."""
    now = datetime.now(timezone.utc)

    q1 = ClarificationQuestion(
        id="q1",
        question="What framework?",
        context="Need to select a frontend framework",
        options=["React", "Vue", "Svelte"],
    )
    q2 = ClarificationQuestion(
        id="q2",
        question="What styling?",
        context="Choose CSS approach",
        options=["Tailwind", "CSS Modules", "Styled Components"],
    )

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=1,
        questions=[q1, q2],
        created_at=now,
    )

    a1 = ClarificationAnswer(
        question_id="q1",
        selected_option="React",
        answered_by="alice",
        answered_at=now,
    )
    a2 = ClarificationAnswer(
        question_id="q2",
        selected_option="Tailwind",
        answered_by="alice",
        answered_at=now,
    )

    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1, a2],
        responded_at=now,
    )

    result, start_line, line_count = format_clarification_artifact(req, resp, "step1", 1)

    # Check return type metadata
    assert start_line == 0
    assert line_count > 0

    # Check header
    assert "## Clarification 1 (Step step1, Attempt 1)" in result
    assert f"**Requested:** {now.isoformat()}" in result

    # Check questions
    assert "### Q1: What framework?" in result
    assert "**Context:** Need to select a frontend framework" in result
    assert "1. React" in result
    assert "2. Vue" in result
    assert "3. Svelte" in result

    assert "### Q2: What styling?" in result
    assert "**Context:** Choose CSS approach" in result
    assert "1. Tailwind" in result

    # Check answers
    assert "**Answer:** React" in result
    assert "**Answer:** Tailwind" in result
    assert "**Answered by:** alice" in result
    assert f"**Answered at:** {now.isoformat()}" in result


def test_format_clarification_artifact_with_free_text():
    """Test formatting with free text answer."""
    now = datetime.now(timezone.utc)

    q1 = ClarificationQuestion(
        id="q1",
        question="Describe the feature",
        context="Need detailed requirements",
        options=["Option A", "Option B", "Other"],
    )

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=2,
        questions=[q1],
        created_at=now,
    )

    a1 = ClarificationAnswer(
        question_id="q1",
        free_text="Custom detailed answer about the feature",
        answered_by="bob",
        answered_at=now,
    )

    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1],
        responded_at=now,
    )

    result, start_line, line_count = format_clarification_artifact(req, resp, "step2", 2)

    assert start_line == 0
    assert line_count > 0
    assert "## Clarification 2 (Step step2, Attempt 2)" in result
    assert "**Answer:** (custom) Custom detailed answer about the feature" in result
    assert "**Answered by:** bob" in result


def test_format_clarification_artifact_unanswered_question():
    """Test formatting when a question hasn't been answered."""
    now = datetime.now(timezone.utc)

    q1 = ClarificationQuestion(
        id="q1",
        question="Question 1",
        context="Context 1",
        options=["A", "B"],
    )
    q2 = ClarificationQuestion(
        id="q2",
        question="Question 2",
        context="Context 2",
        options=["X", "Y"],
    )

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=1,
        questions=[q1, q2],
        created_at=now,
    )

    # Only answer q1
    a1 = ClarificationAnswer(
        question_id="q1",
        selected_option="A",
        answered_by="alice",
        answered_at=now,
    )

    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1],
        responded_at=now,
    )

    result, start_line, line_count = format_clarification_artifact(req, resp, "step1", 1)

    assert start_line == 0
    assert line_count > 0

    # Q1 should have answer
    assert "### Q1: Question 1" in result
    assert "**Answer:** A" in result

    # Q2 should appear but without answer section
    assert "### Q2: Question 2" in result
    assert "**Context:** Context 2" in result
    # Check that the answer markers for Q2 aren't there
    lines = result.split("\n")
    q2_section_start = next(i for i, line in enumerate(lines) if "### Q2:" in line)
    q2_section = lines[q2_section_start : q2_section_start + 10]
    assert not any("**Answer:**" in line for line in q2_section)


def test_build_artifact_header():
    """Test artifact header generation."""
    header = build_artifact_header()
    assert "# Clarifications Log" in header
    assert "Auto-generated by Orchestrator" in header
    assert "Referenced in build/verify phases" in header


def test_resolve_artifact_path_simple():
    """Test simple path template resolution."""
    template = "docs/{{project}}/clarifications.md"
    config = {"project": "myapp"}
    result = resolve_artifact_path(template, config)
    assert result == "docs/myapp/clarifications.md"


def test_resolve_artifact_path_multiple_vars():
    """Test path template with multiple variables."""
    template = "{{base}}/{{project}}/{{step}}/notes.md"
    config = {
        "base": "artifacts",
        "project": "web-app",
        "step": "step1",
    }
    result = resolve_artifact_path(template, config)
    assert result == "artifacts/web-app/step1/notes.md"


def test_resolve_artifact_path_no_vars():
    """Test path template with no variables."""
    template = "docs/clarifications.md"
    config = {"project": "myapp"}
    result = resolve_artifact_path(template, config)
    assert result == "docs/clarifications.md"


def test_resolve_artifact_path_missing_var():
    """Test path template when config doesn't have a variable."""
    template = "docs/{{project}}/{{missing}}/file.md"
    config = {"project": "myapp"}
    result = resolve_artifact_path(template, config)
    # Missing vars remain as-is
    assert result == "docs/myapp/{{missing}}/file.md"


def test_resolve_artifact_path_with_int_values():
    """Test path template with integer values in config."""
    template = "artifacts/run-{{run_id}}/step-{{step_num}}.md"
    config = {"run_id": 123, "step_num": 5}
    result = resolve_artifact_path(template, config)
    assert result == "artifacts/run-123/step-5.md"


# --- ClarificationQuestion validator tests ---


def test_validator_free_text_with_options_raises():
    """question_type='free_text' with non-empty options raises ValidationError."""
    with pytest.raises(ValidationError, match="options.*must be empty"):
        ClarificationQuestion(
            id="q1",
            question="Describe it",
            context="Context",
            options=["A", "B"],
            question_type="free_text",
        )


def test_validator_single_select_empty_options_raises():
    """question_type='single_select' with empty options raises ValidationError."""
    with pytest.raises(ValidationError, match="options.*must be non-empty"):
        ClarificationQuestion(
            id="q1",
            question="Pick one",
            context="Context",
            options=[],
            question_type="single_select",
        )


def test_validator_number_min_greater_than_max_raises():
    """question_type='number' with min=5, max=2 raises ValidationError."""
    with pytest.raises(ValidationError, match="min.*<=.*max"):
        ClarificationQuestion(
            id="q1",
            question="Enter a number",
            context="Context",
            options=[],
            question_type="number",
            min=5,
            max=2,
        )


def test_validator_single_select_valid():
    """question_type='single_select' with non-empty options succeeds."""
    q = ClarificationQuestion(
        id="q1",
        question="Pick one",
        context="Context",
        options=["A", "B"],
        question_type="single_select",
    )
    assert q.question_type == "single_select"
    assert q.options == ["A", "B"]


def test_validator_multi_select_valid():
    """question_type='multi_select' with non-empty options succeeds."""
    q = ClarificationQuestion(
        id="q1",
        question="Pick many",
        context="Context",
        options=["X", "Y", "Z"],
        question_type="multi_select",
    )
    assert q.question_type == "multi_select"
    assert q.options == ["X", "Y", "Z"]


def test_validator_free_text_valid():
    """question_type='free_text' with no options succeeds."""
    q = ClarificationQuestion(
        id="q1",
        question="Describe it",
        context="Context",
        options=[],
        question_type="free_text",
    )
    assert q.question_type == "free_text"
    assert q.options == []


def test_validator_number_valid():
    """question_type='number' with appropriate min/max succeeds."""
    q = ClarificationQuestion(
        id="q1",
        question="Enter a number",
        context="Context",
        options=[],
        question_type="number",
        min=1,
        max=10,
    )
    assert q.question_type == "number"
    assert q.min == 1
    assert q.max == 10


def test_format_clarification_artifact_with_multi_select_options():
    """Test formatting artifact with selected_options (multi-select) renders both selections."""
    now = datetime.now(timezone.utc)

    q1 = ClarificationQuestion(
        id="q1",
        question="Which frameworks do you want?",
        context="Select all that apply",
        options=["A", "B", "C"],
        question_type="multi_select",
    )

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=1,
        questions=[q1],
        created_at=now,
    )

    a1 = ClarificationAnswer(
        question_id="q1",
        selected_options=["A", "B"],
        answered_by="alice",
        answered_at=now,
    )

    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1],
        responded_at=now,
    )

    result, start_line, line_count = format_clarification_artifact(req, resp, "step1", 1)

    assert start_line == 0
    assert line_count > 0
    assert "A, B" in result
    assert "**Answer:** A, B" in result


def test_format_clarification_artifact_with_skipped_answer():
    """Test formatting artifact with skipped=True renders skipped answer with reason."""
    now = datetime.now(timezone.utc)

    q1 = ClarificationQuestion(
        id="q1",
        question="Optional preference?",
        context="This can be skipped",
        options=["Yes", "No"],
        required=False,
    )

    req = ClarificationRequest(
        id="req1",
        run_id="run123",
        task_id="task456",
        attempt_num=1,
        questions=[q1],
        created_at=now,
    )

    a1 = ClarificationAnswer(
        question_id="q1",
        skipped=True,
        skip_reason="Not needed",
        answered_by="alice",
        answered_at=now,
    )

    resp = ClarificationResponse(
        request_id="req1",
        answers=[a1],
        responded_at=now,
    )

    result, start_line, line_count = format_clarification_artifact(req, resp, "step1", 1)

    assert start_line == 0
    assert line_count > 0
    assert "(skipped)" in result
    assert "Not needed" in result
