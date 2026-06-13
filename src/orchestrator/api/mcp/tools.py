"""MCP tool definitions and handler for orchestrator operations.

ToolHandler dispatches tool calls to WorkflowService methods.
It is tested independently of server transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.config.enums import ChecklistStatus
from orchestrator.git import get_repo, list_branches, list_repos
from orchestrator.git.repos import RepoNotFoundError
from orchestrator.api.mcp.clarification_tools import (
    CLARIFICATION_TOOL,
    validate_clarification_question_payloads,
)
from orchestrator.time_utils import format_utc_datetime
from orchestrator.workflow import (
    ClarificationQuestion,
)
from orchestrator.workflow.service import WorkflowService


# JSON schemas for the orchestrator MCP tools
ORCHESTRATOR_TOOLS: list[dict[str, Any]] = [
    {
        "name": "orchestrator_get_requirements",
        "description": "Get the list of requirements (checklist items) for a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["run_id", "task_id"],
        },
    },
    {
        "name": "orchestrator_update_checklist",
        "description": "Mark a requirement as done, not applicable, or blocked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
                "req_id": {"type": "string", "description": "The requirement ID"},
                "status": {
                    "type": "string",
                    "description": "New status: done, not_applicable, or blocked",
                    "enum": ["done", "not_applicable", "blocked"],
                },
                "note": {
                    "type": "string",
                    "description": "Optional note about the update",
                },
            },
            "required": ["run_id", "task_id", "req_id", "status"],
        },
    },
    {
        "name": "orchestrator_submit",
        "description": "Submit the task for verification after completing requirements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["run_id", "task_id"],
        },
    },
    {
        "name": "orchestrator_set_grade",
        "description": "Set a grade for a requirement (used by verifier).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
                "req_id": {"type": "string", "description": "The requirement ID"},
                "grade": {
                    "type": "string",
                    "description": "Grade value (e.g., A, B, C, D, F)",
                },
                "grade_reason": {
                    "type": "string",
                    "description": "Optional reason for the grade",
                },
            },
            "required": ["run_id", "task_id", "req_id", "grade"],
        },
    },
    {
        "name": "orchestrator_complete_recovery",
        "description": "Complete recovery for a task that entered a failure state. Choose an outcome: retry (re-attempt the task), skip (mark as completed/skipped), or abandon (mark as permanently failed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
                "outcome": {
                    "type": "string",
                    "description": "Recovery outcome: retry, skip, or abandon",
                    "enum": ["retry", "skip", "abandon"],
                },
                "notes": {
                    "type": "string",
                    "description": "Explanation of the recovery decision",
                },
            },
            "required": ["run_id", "task_id", "outcome", "notes"],
        },
    },
    CLARIFICATION_TOOL,
    {
        "name": "orchestrator_escalate_requirement",
        "description": "Flag a requirement as unfulfillable and pause the run for human review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run ID"},
                "task_id": {"type": "string", "description": "The task ID"},
                "requirement_id": {
                    "type": "string",
                    "description": "The requirement ID to escalate",
                },
                "reason": {
                    "type": "string",
                    "description": "Explanation of why this requirement cannot be fulfilled",
                },
            },
            "required": ["run_id", "task_id", "requirement_id", "reason"],
        },
    },
    {
        "name": "orchestrator_list_repos",
        "description": "List available repositories in the repos directory.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "orchestrator_list_branches",
        "description": "List branches in a repository with optional glob pattern filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of the repository"},
                "pattern": {
                    "type": "string",
                    "description": "Optional glob pattern to filter branches (e.g., 'feat*', '*/auth')",
                },
                "local_only": {
                    "type": "boolean",
                    "description": "If true, only list local branches (default: false)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of branches to return (default: 100)",
                },
            },
            "required": ["repo_name"],
        },
    },
    {
        "name": "orchestrator_wait_for_run",
        "description": (
            "Wait for a run to complete, fail, or pause, then return its current status. "
            "If timed_out is true, you may call again with another bounded wait, but "
            "after a few consecutive timeouts on the same child, escalate the "
            "requirement instead of polling indefinitely."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID to observe"},
                "timeout_seconds": {
                    "type": "number",
                    "description": "Maximum seconds to wait, capped at 600",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "orchestrator_get_run_evidence",
        "description": "Return structured run.evidence.v1 bundles from a run worktree.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID to inspect"},
            },
            "required": ["run_id"],
        },
    },
]


class ToolHandler:
    """Dispatches MCP tool calls to WorkflowService methods."""

    def __init__(
        self,
        service: WorkflowService,
        repos_dir: Path | None = None,
    ) -> None:
        self._service = service
        self._repos_dir = repos_dir

    async def handle(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call and return the result as a dict.

        Raises:
            ValueError: If the tool name is unknown.
        """
        if tool_name == "orchestrator_get_requirements":
            return await self._get_requirements(arguments)
        elif tool_name == "orchestrator_update_checklist":
            return await self._update_checklist(arguments)
        elif tool_name == "orchestrator_submit":
            return await self._submit(arguments)
        elif tool_name == "orchestrator_set_grade":
            return await self._set_grade(arguments)
        elif tool_name == "orchestrator_complete_recovery":
            return await self._complete_recovery(arguments)
        elif tool_name == "orchestrator_request_clarification":
            return await self._request_clarification(arguments)
        elif tool_name == "orchestrator_escalate_requirement":
            return await self._escalate_requirement(arguments)
        elif tool_name == "orchestrator_list_repos":
            return await self._list_repos(arguments)
        elif tool_name == "orchestrator_list_branches":
            return await self._list_branches(arguments)
        elif tool_name == "orchestrator_wait_for_run":
            return await self._wait_for_run(arguments)
        elif tool_name == "orchestrator_get_run_evidence":
            return await self._get_run_evidence(arguments)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def _get_requirements(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        task = await self._service.get_task(run_id, task_id)
        return {
            "requirements": [
                {
                    "req_id": item.req_id,
                    "desc": item.desc,
                    "priority": item.priority.value,
                    "status": item.status.value,
                    "note": item.note,
                    "grade": item.grade,
                    "grade_reason": item.grade_reason,
                }
                for item in task.checklist
            ]
        }

    async def _update_checklist(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        req_id: str = args["req_id"]
        status = ChecklistStatus(args["status"])
        note: str | None = args.get("note")

        item = await self._service.update_checklist_item(run_id, task_id, req_id, status, note)
        return {
            "req_id": item.req_id,
            "status": item.status.value,
            "note": item.note,
        }

    async def _submit(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        # If the run is already paused for human review (escalation or
        # clarification), treat submit as a no-op success instead of letting
        # submit_for_verification raise InvalidTransitionError. Surfacing the
        # error wraps to AgentExecutionError and falsely marks the attempt
        # failed even though escalation was the correct outcome.
        run = await self._service.get_run(run_id)
        if run.status.value == "paused" and run.pause_reason in (
            "requirement_escalated",
            "awaiting_clarification",
        ):
            return {
                "success": True,
                "new_status": "paused",
                "error": None,
                "run_paused": True,
                "pause_reason": run.pause_reason,
                "skipped": True,
                "message": (
                    "Run is paused for human review; submission deferred. "
                    "Stop calling tools and exit cleanly."
                ),
            }
        result = await self._service.submit_for_verification(run_id, task_id)
        return {
            "success": result.success,
            "new_status": result.new_status.value,
            "error": result.error,
        }

    async def _set_grade(self, args: dict[str, Any]) -> dict[str, Any]:
        from orchestrator.workflow import InvalidTransitionError

        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        req_id: str = args["req_id"]
        grade: str = args["grade"]
        grade_reason: str | None = args.get("grade_reason")

        # If the verifier escalated a requirement earlier in this session, the
        # run is already PAUSED for human review. Any further set_grade /
        # submit calls are best-effort tail work — treat them as no-op success
        # so we don't surface a transition error and trigger the agent's
        # exception handler. The escalate response already signalled
        # `next_action: stop`.
        run = await self._service.get_run(run_id)
        if run.status.value == "paused" and run.pause_reason == "requirement_escalated":
            return {
                "req_id": req_id,
                "grade": grade,
                "grade_reason": grade_reason,
                "run_paused": True,
                "skipped": True,
                "message": (
                    "Run is paused for human review of an escalated requirement; "
                    "grade not applied. Stop calling tools and exit cleanly."
                ),
            }

        try:
            item = await self._service.set_grade(run_id, task_id, req_id, grade, grade_reason)
        except InvalidTransitionError as exc:
            return {
                "error": str(exc),
                "hint": (
                    "set_grade is only available during the VERIFYING phase. "
                    "If you are the builder agent, finish your work and call "
                    "orchestrator_submit first. Grading happens after submission."
                ),
            }
        return {
            "req_id": item.req_id,
            "grade": item.grade,
            "grade_reason": item.grade_reason,
        }

    async def _complete_recovery(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        outcome: str = args["outcome"]
        notes: str = args["notes"]

        if outcome not in ("retry", "skip", "abandon"):
            raise ValueError(
                f"Invalid recovery outcome '{outcome}'. Must be one of: retry, skip, abandon"
            )

        if outcome == "retry":
            result = await self._service.complete_recovery_retry(run_id, task_id, notes)
        elif outcome == "skip":
            result = await self._service.complete_recovery_skip(run_id, task_id, notes)
        else:
            result = await self._service.complete_recovery_abandon(run_id, task_id, notes)

        return {
            "success": result.success,
            "new_status": result.new_status.value,
            "outcome": outcome,
            "notes": notes,
        }

    async def _request_clarification(self, args: dict[str, Any]) -> dict[str, Any]:
        import uuid

        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        questions_data: list[dict[str, Any]] = args["questions"]

        validate_clarification_question_payloads(questions_data)

        # Convert dict questions to ClarificationQuestion objects
        questions = [
            ClarificationQuestion(
                id=str(uuid.uuid4()),
                question=q["question"],
                context=q["context"],
                options=q.get("options", []),
                question_type=q.get("question_type", "single_select"),
                allow_other=q.get("allow_other", True),
                required=q.get("required", True),
                min=q.get("min"),
                max=q.get("max"),
                placeholder=q.get("placeholder"),
            )
            for q in questions_data
        ]

        # Request clarification via service
        request = await self._service.request_clarification(run_id, task_id, questions)

        return {
            "request_id": request.id,
            "run_id": request.run_id,
            "task_id": request.task_id,
            "questions": [
                {
                    "id": q.id,
                    "question": q.question,
                    "context": q.context,
                    "options": q.options,
                    "question_type": q.question_type,
                    "allow_other": q.allow_other,
                    "required": q.required,
                    "min": q.min,
                    "max": q.max,
                    "placeholder": q.placeholder,
                }
                for q in request.questions
            ],
            "created_at": format_utc_datetime(request.created_at),
            "run_paused": True,
            "do_not_submit": True,
            "next_action": "stop",
            "message": (
                "Clarification requested. Run is PAUSED awaiting human response. "
                "STOP NOW: do not call orchestrator_submit, do not continue working. "
                "Exit cleanly. The orchestrator will resume this attempt with the "
                "human's answer in the next prompt."
            ),
        }

    async def _escalate_requirement(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        requirement_id: str = args["requirement_id"]
        reason: str = args["reason"]

        run = await self._service.escalate_requirement(run_id, task_id, requirement_id, reason)
        return {
            "run_id": run.id,
            "status": run.status.value,
            "pause_reason": run.pause_reason,
            "requirement_id": requirement_id,
            "reason": reason,
            "run_paused": True,
            "do_not_submit": True,
            "next_action": "stop",
            "message": (
                "Requirement escalated. Run is PAUSED for human review. "
                "STOP NOW: do not call orchestrator_submit, do not continue working. "
                "Exit cleanly. The orchestrator will resume this attempt after the "
                "human responds."
            ),
        }

    async def _list_repos(self, args: dict[str, Any]) -> dict[str, Any]:
        """List available repositories."""
        if self._repos_dir is None:
            return {"error": "repos_dir not configured", "repos": []}

        try:
            repos = list_repos(self._repos_dir)
            return {
                "repos": [
                    {
                        "name": repo.name,
                        "path": str(repo.path),
                        "default_branch": repo.default_branch,
                    }
                    for repo in repos
                ]
            }
        except Exception as e:
            return {"error": str(e), "repos": []}

    async def _list_branches(self, args: dict[str, Any]) -> dict[str, Any]:
        """List branches in a repository."""
        if self._repos_dir is None:
            return {"error": "repos_dir not configured", "branches": []}

        repo_name: str = args["repo_name"]
        pattern: str = args.get("pattern", "")
        local_only: bool = args.get("local_only", False)
        limit: int = args.get("limit", 100)

        try:
            repo = get_repo(self._repos_dir, repo_name)
            branches = list_branches(
                repo.path,
                pattern=pattern,
                local_only=local_only,
                limit=limit,
            )
            return {
                "repo_name": repo_name,
                "pattern": pattern,
                "branches": [
                    {
                        "name": b.name,
                        "is_remote": b.is_remote,
                        "commit": b.commit,
                    }
                    for b in branches
                ],
                "total": len(branches),
                "truncated": len(branches) == limit,
            }
        except RepoNotFoundError as e:
            return {"error": str(e), "branches": []}
        except Exception as e:
            return {"error": str(e), "branches": []}

    async def _wait_for_run(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        requested_timeout_seconds = float(args.get("timeout_seconds", 0))
        # Cap raised from 300s -> 600s. Long-running child plan/build phases
        # routinely exceed 5 minutes; the prior cap forced parents into a
        # one-wait-then-submit pattern that produced "blocked, no evidence"
        # verifier failures. Keep the cap below the nudger kill window
        # (default 600s kill_after_seconds).
        timeout_seconds = min(requested_timeout_seconds, 600.0)
        run = await self._service.wait_for_run_terminal(run_id, timeout_seconds)
        terminal = run.status.value in ("completed", "failed")
        meaningful_state = terminal or run.status.value == "paused"
        return {
            "run_id": run.id,
            "status": run.status.value,
            "terminal": terminal,
            "meaningful_state": meaningful_state,
            "timed_out": timeout_seconds > 0 and not meaningful_state,
            "timeout_seconds": timeout_seconds,
            "requested_timeout_seconds": requested_timeout_seconds,
            "pause_reason": run.pause_reason,
            "last_error": run.last_error,
        }

    async def _get_run_evidence(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        return await self._service.collect_validated_run_evidence(run_id)
