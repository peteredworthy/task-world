"""MCP tool definitions for clarification requests.

Provides tools for agents to request clarification from humans during
task execution.
"""

import re
from typing import Any

CLARIFICATION_AUTHORING_GUIDE = (
    "Ask concise human-facing decision questions. The context must explain: "
    "Parent needed: what the parent was trying to decide or prove; "
    "Child did: what the child actually reported or changed; "
    "Decision needed: what the human must choose now. Translate internal IDs into "
    "plain-language labels; IDs may appear only alongside those labels. For finite "
    "decisions, use question_type='single_select' or 'multi_select' and put each "
    "actual option in options. Do not embed '(a)/(b)/(c)' choices in a free_text "
    "question. Use free_text only for genuinely open-ended input."
)

_FINITE_CHOICE_MARKER = re.compile(r"(?:\([a-z]\)|\b[a-z]\)|\boption\s+[a-z]\b)", re.IGNORECASE)
_FINITE_CHOICE_VERB = re.compile(r"\b(?:choose|pick|select)\b", re.IGNORECASE)


def validate_clarification_question_payloads(questions: list[dict[str, Any]]) -> None:
    """Reject question payloads that encode finite choices as free text."""

    for index, question in enumerate(questions, start=1):
        question_type = question.get("question_type", "single_select")
        question_text = str(question.get("question", ""))
        choice_markers = _FINITE_CHOICE_MARKER.findall(question_text)
        looks_like_finite_choice = len(choice_markers) >= 2 or (
            bool(choice_markers) and bool(_FINITE_CHOICE_VERB.search(question_text))
        )
        if question_type == "free_text" and looks_like_finite_choice:
            raise ValueError(
                f"Clarification question {index} looks like a finite choice but uses "
                "question_type='free_text'. Use question_type='single_select' or "
                "'multi_select', put each actual option in options, and keep the "
                "question/context separate from the option list."
            )


CLARIFICATION_TOOL: dict[str, Any] = {
    "name": "orchestrator_request_clarification",
    "description": (
        "Request clarification from the human. "
        "The task will pause until the human answers. "
        "Answers will be appended to the clarifications artifact file. "
        + CLARIFICATION_AUTHORING_GUIDE
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "The run ID"},
            "task_id": {"type": "string", "description": "The task ID"},
            "questions": {
                "type": "array",
                "description": "Questions needing answers",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "A concise human-facing prompt for the decision. "
                                "Do not include a/b/c option text here; use options."
                            ),
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "Brief context using: Parent needed; Child did; "
                                "Decision needed. Explain internal IDs in human terms."
                            ),
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "2-4 actual choices for single_select or multi_select. "
                                "Each option should state the decision and consequence."
                            ),
                            "minItems": 2,
                            "maxItems": 4,
                        },
                        "question_type": {
                            "type": "string",
                            "enum": ["single_select", "multi_select", "free_text", "number"],
                            "default": "single_select",
                            "description": (
                                "Use single_select for one finite choice, multi_select for "
                                "multiple finite choices, free_text only for open-ended input."
                            ),
                        },
                        "allow_other": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether to show a free-text 'Other' option for select types.",
                        },
                        "required": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether an answer is required. If False, the user may skip.",
                        },
                        "min": {
                            "type": ["number", "null"],
                            "default": None,
                            "description": "Minimum value for number question type.",
                        },
                        "max": {
                            "type": ["number", "null"],
                            "default": None,
                            "description": "Maximum value for number question type.",
                        },
                        "placeholder": {
                            "type": ["string", "null"],
                            "default": None,
                            "description": "Placeholder text for free_text or number inputs.",
                        },
                    },
                    "required": ["question", "context"],
                },
            },
        },
        "required": ["run_id", "task_id", "questions"],
    },
}
