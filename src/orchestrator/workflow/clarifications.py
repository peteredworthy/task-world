"""Clarification models and artifact generation (pure functions)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class ClarificationQuestion(BaseModel):
    """A question from the builder needing human input."""

    id: str = ""
    question: str = ""
    context: str = ""
    options: list[str] = []  # Multi-choice options (2-4)
    question_type: Literal["single_select", "multi_select", "free_text", "number"] = "single_select"
    allow_other: bool = True
    required: bool = True
    min: float | None = None
    max: float | None = None
    placeholder: str | None = None

    @model_validator(mode="after")
    def validate_options_for_type(self) -> "ClarificationQuestion":
        if self.question_type in ("single_select", "multi_select"):
            if not self.options:
                raise ValueError(
                    f"'options' must be non-empty for question_type={self.question_type!r}"
                )
        else:  # free_text, number
            if self.options:
                raise ValueError(
                    f"'options' must be empty for question_type={self.question_type!r}"
                )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' must be <= 'max'")
        return self


class ClarificationAnswer(BaseModel):
    """Human's answer to a clarification question."""

    question_id: str
    selected_option: str | None = None
    free_text: str | None = None
    answered_by: str
    answered_at: datetime
    selected_options: list[str] | None = None
    skipped: bool = False
    skip_reason: str | None = None


class ClarificationRequest(BaseModel):
    """A set of questions from builder needing answers."""

    id: str
    run_id: str
    task_id: str
    attempt_num: int
    questions: list[ClarificationQuestion]
    created_at: datetime
    responded_at: datetime | None = None


class ClarificationResponse(BaseModel):
    """Human's answers to a clarification request."""

    request_id: str
    answers: list[ClarificationAnswer]
    responded_at: datetime


@dataclass
class CompressedDecision:
    """A single decision extracted from a Q&A pair (template-based, no LLM)."""

    question: str
    decision: str
    rationale: str


@dataclass
class CompressedDecisions:
    """Compressed decisions extracted from one clarification round."""

    decisions: list[CompressedDecision] = field(default_factory=lambda: [])
    source_request_id: str = ""


def compress_clarifications(
    request: ClarificationRequest,
    response: ClarificationResponse,
) -> CompressedDecisions:
    """Extract compact decisions from resolved Q&A (template-based, no LLM).

    Transforms raw question/answer pairs into a compact decision + rationale
    format suitable for embedding directly in downstream prompts.

    The raw Q&A is archived separately (in the artifact file); this function
    produces the compact form that prompt assembly should use.

    Pure function - no I/O.
    """
    decisions: list[CompressedDecision] = []

    for q in request.questions:
        answer = next((a for a in response.answers if a.question_id == q.id), None)
        if answer is None:
            continue

        if answer.skipped:
            reason = answer.skip_reason or ""
            decision = f"(skipped){': ' + reason if reason else ''}"
        elif answer.free_text:
            decision = answer.free_text
        elif answer.selected_options is not None:
            decision = ", ".join(answer.selected_options)
        elif answer.selected_option:
            decision = answer.selected_option
        else:
            continue

        decisions.append(
            CompressedDecision(
                question=q.question,
                decision=decision,
                rationale=q.context,
            )
        )

    return CompressedDecisions(
        decisions=decisions,
        source_request_id=request.id,
    )


def decisions_from_config(config: dict[str, Any]) -> CompressedDecisions | None:
    """Reconstruct CompressedDecisions from run.config['_compressed_decisions'].

    Returns None if the key is absent or the data is malformed.
    """
    raw = config.get("_compressed_decisions")
    if not isinstance(raw, list):
        return None
    entries: list[dict[str, str]] = raw  # type: ignore[assignment]
    try:
        decisions: list[CompressedDecision] = []
        for d in entries:
            decisions.append(
                CompressedDecision(
                    question=d["question"],
                    decision=d["decision"],
                    rationale=d["rationale"],
                )
            )
        return CompressedDecisions(
            decisions=decisions,
            source_request_id=config.get("_compressed_decisions_request_id", ""),
        )
    except (KeyError, TypeError):
        return None


def format_clarification_artifact(
    request: ClarificationRequest,
    response: ClarificationResponse,
    step_id: str,
    clarification_number: int,
) -> tuple[str, int, int]:
    """Format clarification Q&A as markdown section for artifact file.

    Pure function - no I/O.

    Returns:
        A tuple of (text, start_line, line_count) where start_line is a
        placeholder (0) to be replaced by the caller after reading the
        current file length.
    """
    lines = [
        f"## Clarification {clarification_number} (Step {step_id}, Attempt {request.attempt_num})",
        f"**Requested:** {request.created_at.isoformat()}",
        "",
    ]

    for i, q in enumerate(request.questions, 1):
        answer = next((a for a in response.answers if a.question_id == q.id), None)

        lines.append(f"### Q{i}: {q.question}")
        lines.append(f"**Context:** {q.context}")
        lines.append("**Options:**")
        for j, opt in enumerate(q.options, 1):
            lines.append(f"{j}. {opt}")
        lines.append("")

        if answer:
            if answer.skipped:
                reason = answer.skip_reason or ""
                lines.append(f"**Answer:** (skipped) {reason}".rstrip())
            elif answer.free_text:
                lines.append(f"**Answer:** (custom) {answer.free_text}")
            elif answer.selected_options is not None:
                lines.append(f"**Answer:** {', '.join(answer.selected_options)}")
            elif answer.selected_option:
                lines.append(f"**Answer:** {answer.selected_option}")
            lines.append(f"**Answered by:** {answer.answered_by}")
            lines.append(f"**Answered at:** {answer.answered_at.isoformat()}")
        lines.append("")

    text = "\n".join(lines)
    line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    return text, 0, line_count


def build_artifact_header() -> str:
    """Build the header for a new clarifications artifact file."""
    return """# Clarifications Log
<!-- Auto-generated by Orchestrator. Referenced in build/verify phases. -->

"""


def resolve_artifact_path(template: str, config: dict[str, Any]) -> str:
    """Resolve {{variable}} placeholders in artifact path template.

    Pure function - no I/O.
    """
    result = template
    for key, value in config.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result
