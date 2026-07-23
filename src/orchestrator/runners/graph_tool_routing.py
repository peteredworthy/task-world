"""Graph tool call routing and payload normalization.

Shared by every graph-capable runner adapter (codex_server, claude_cli).
All graph tools an LLM can call — ``submit_graph_patch`` plus 8 "macro"
tools that create/attach graph nodes and regions — normalize through the
same ``GraphPatchCallback`` (a single closure the graph dispatcher builds
per in-flight execution). This module owns that normalization so no
adapter has to duplicate it.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from orchestrator.config.enums import ChecklistStatus
from orchestrator.runners.types import (
    ChecklistUpdateCallback,
    CompleteRecoveryCallback,
    GradeCallback,
    GraphPatchCallback,
    SubmitCallback,
)

logger = logging.getLogger(__name__)

GRAPH_MACRO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_work_region",
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
    }
)


def is_allowed_tool(tool_name: str, allowlist: frozenset[str]) -> bool:
    return tool_name in allowlist


def enforce_tool_allowlist(tool_name: str, allowlist: frozenset[str]) -> None:
    if not is_allowed_tool(tool_name, allowlist):
        raise ValueError(f"Tool '{tool_name}' is not on the allow-list")


async def route_tool_call(
    tool_name: str,
    args: dict[str, Any],
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_submit_graph_patch: GraphPatchCallback | None = None,
    on_grade: GradeCallback | None = None,
    on_complete_recovery: CompleteRecoveryCallback | None = None,
    *,
    allowlist: frozenset[str],
    agent_label: str = "GraphRunner",
) -> str:
    """Route an allow-listed callback tool call to the appropriate callback.

    Tool routing:
    - ``update_checklist`` -> ``on_checklist_update(req_id, status, note)``
    - ``submit``           -> ``on_submit()``
    - ``submit_graph_patch`` -> ``on_submit_graph_patch(payload)``
    - a name in ``GRAPH_MACRO_TOOL_NAMES`` -> ``on_submit_graph_patch(payload)``
      after macro-specific normalization
    - ``grade``            -> ``on_grade(req_id, grade, grade_reason)`` (verifier only)
    - ``request_clarification`` -> logged; no callback
    - ``complete_recovery`` -> ``on_complete_recovery(outcome, notes)``

    Raises:
        ValueError: If ``tool_name`` is not on ``allowlist``.
    """
    enforce_tool_allowlist(tool_name, allowlist)

    if tool_name == "update_checklist":
        req_id: str = str(args.get("req_id", "")).strip()
        if not req_id:
            raise ValueError("update_checklist requires a non-empty 'req_id'")
        raw_status: str = str(args.get("status", "done"))
        note: str | None = args.get("note")
        status = ChecklistStatus(raw_status)
        await on_checklist_update(req_id, status, note)
        return ""

    if tool_name == "submit":
        await on_submit()
        return ""

    if tool_name == "submit_graph_patch":
        if on_submit_graph_patch is None:
            raise ValueError("submit_graph_patch is not registered for this session")
        payload = normalize_patch_payload(args)
        return await on_submit_graph_patch(payload)

    if tool_name in GRAPH_MACRO_TOOL_NAMES:
        if on_submit_graph_patch is None:
            raise ValueError(f"{tool_name} is not registered for this session")
        payload = normalize_macro_tool_payload(tool_name, args)
        return await on_submit_graph_patch(payload)

    if tool_name == "grade":
        if on_grade is not None:
            req_id = str(args.get("req_id", "")).strip()
            grade: str = str(args.get("grade", "")).strip()
            if not req_id:
                raise ValueError("grade requires a non-empty 'req_id'")
            if not grade:
                raise ValueError("grade requires a non-empty 'grade'")
            grade_reason: str | None = args.get("grade_reason")
            await on_grade(req_id, grade, grade_reason)
        else:
            logger.warning("%s: 'grade' tool called in builder phase — ignoring", agent_label)
        return ""

    if tool_name == "request_clarification":
        question: str = str(args.get("question", ""))
        logger.info("%s: request_clarification received — question=%r", agent_label, question)
        return ""

    if tool_name == "complete_recovery":
        outcome: str = str(args.get("outcome", "retry"))
        notes: str | None = args.get("notes")
        if on_complete_recovery is not None:
            await on_complete_recovery(outcome, notes)
        else:
            logger.info(
                "%s: complete_recovery called (outcome=%r) but no callback registered — ignoring",
                agent_label,
                outcome,
            )
        return ""

    return ""


def normalize_macro_tool_payload(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    patch_id = args.get("patch_id")
    base_graph_position = args.get("base_graph_position")
    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError(f"{tool_name} requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError(f"{tool_name} requires integer base_graph_position")

    macro_args = {
        key: value
        for key, value in args.items()
        if key not in {"patch_id", "base_graph_position", "rationale_record_id"}
    }
    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "macro_invocations": [{"macro": tool_name, "args": macro_args}],
    }
    rationale_record_id = args.get("rationale_record_id")
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload


def normalize_patch_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Normalize planner patch arguments into a top-level PatchEnvelope payload."""
    if "patch" in args:
        if len(args) != 1:
            raise ValueError("submit_graph_patch accepts either `patch` or patch fields, not both")
        raw_patch = args.get("patch")
        if not isinstance(raw_patch, dict):
            raise ValueError("submit_graph_patch requires `patch` to be an object")
        patch = cast(dict[str, Any], raw_patch)
        patch_id = patch.get("patch_id")
        base_graph_position = patch.get("base_graph_position")
        ops = patch.get("ops")
        rationale_record_id = patch.get("rationale_record_id")
    else:
        patch_id = args.get("patch_id")
        base_graph_position = args.get("base_graph_position")
        ops = args.get("ops")
        rationale_record_id = args.get("rationale_record_id")

    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError("submit_graph_patch requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError("submit_graph_patch requires integer base_graph_position")
    if not isinstance(ops, list):
        raise ValueError("submit_graph_patch requires an ops list")

    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "ops": ops,
    }
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload
