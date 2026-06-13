"""Unit tests for MCP tool definitions — pure, zero I/O."""

import pytest

from orchestrator.api import ORCHESTRATOR_TOOLS, validate_clarification_question_payloads


def test_tool_definitions_well_formed() -> None:
    """Verify tool definitions have required fields."""
    assert len(ORCHESTRATOR_TOOLS) == 11

    for tool in ORCHESTRATOR_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"
        assert "properties" in tool["inputSchema"]
        assert "required" in tool["inputSchema"]

    names = {t["name"] for t in ORCHESTRATOR_TOOLS}
    assert names == {
        "orchestrator_get_requirements",
        "orchestrator_update_checklist",
        "orchestrator_submit",
        "orchestrator_set_grade",
        "orchestrator_complete_recovery",
        "orchestrator_request_clarification",
        "orchestrator_escalate_requirement",
        "orchestrator_list_repos",
        "orchestrator_list_branches",
        "orchestrator_wait_for_run",
        "orchestrator_get_run_evidence",
    }


def test_clarification_tool_guides_human_facing_select_questions() -> None:
    tool = next(t for t in ORCHESTRATOR_TOOLS if t["name"] == "orchestrator_request_clarification")
    description = tool["description"]
    question_props = tool["inputSchema"]["properties"]["questions"]["items"]["properties"]

    assert "Parent needed" in description
    assert "Child did" in description
    assert "Decision needed" in description
    assert "single_select" in description
    assert "multi_select" in description
    assert "free_text only for genuinely open-ended input" in description
    assert "Do not include a/b/c option text here" in question_props["question"]["description"]
    assert (
        "Each option should state the decision and consequence"
        in (question_props["options"]["description"])
    )


def test_free_text_clarification_rejects_embedded_finite_choices() -> None:
    with pytest.raises(ValueError, match="finite choice"):
        validate_clarification_question_payloads(
            [
                {
                    "question": "Pick: (a) accept it; (b) retry it; or (c) abandon it.",
                    "context": "Parent needed: decide. Child did: stopped. Decision needed: choose.",
                    "question_type": "free_text",
                    "options": [],
                }
            ]
        )


def test_select_clarification_allows_explicit_options() -> None:
    validate_clarification_question_payloads(
        [
            {
                "question": "How should the parent handle the child result?",
                "context": (
                    "Parent needed: decide whether to accept a child slice. Child did: "
                    "returned valid evidence. Decision needed: choose the next parent action."
                ),
                "question_type": "single_select",
                "options": ["Accept the child", "Retry with more evidence", "Reject and replan"],
            }
        ]
    )
