"""Unit tests for clarification models and pure functions."""

from datetime import datetime, timezone


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

    result = format_clarification_artifact(req, resp, "step1", 1)

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

    result = format_clarification_artifact(req, resp, "step2", 2)

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

    result = format_clarification_artifact(req, resp, "step1", 1)

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
