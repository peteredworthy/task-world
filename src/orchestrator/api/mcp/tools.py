"""MCP tool definitions and handler for orchestrator operations.

ToolHandler dispatches tool calls to WorkflowService methods.
It is tested independently of server transport.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from orchestrator.config import RoutineConfig
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus, RoutineSource
from orchestrator.git import get_repo, list_branches, list_repos
from orchestrator.git.repos import RepoNotFoundError
from orchestrator.api.mcp.clarification_tools import (
    CLARIFICATION_TOOL,
    validate_clarification_question_payloads,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state import Run
from orchestrator.time_utils import format_utc_datetime
from orchestrator.workflow import (
    ChildSliceSpec,
    ClarificationQuestion,
    compile_child_routine_from_spec,
)
from orchestrator.workflow.service import WorkflowService


def _resolve_child_source_branch(parent_run: Run, requested_branch: str | None) -> str:
    """Resolve the branch to use when creating an oversight child run.

    Prefer the parent accumulation branch when present in the parent worktree,
    then honor an explicit branch if no accumulation branch exists.
    """

    parent_accum_branch = f"orchestrator/run-{parent_run.id}"
    if parent_run.worktree_path:
        try:
            branches = list_branches(Path(parent_run.worktree_path), local_only=True)
        except (OSError, subprocess.CalledProcessError):
            branches = []
        else:
            if any(branch.name == parent_accum_branch for branch in branches):
                return parent_accum_branch

    if requested_branch:
        return requested_branch

    return parent_run.source_branch or "main"


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
        "name": "orchestrator_create_child_run",
        "description": "Create an oversight child run from an embedded routine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_run_id": {"type": "string", "description": "Parent oversight run ID"},
                "parent_slice_id": {"type": "string", "description": "Slice ID for this child"},
                "routine_embedded": {
                    "type": "object",
                    "description": "Embedded routine config for the child run",
                },
                "repo_name": {"type": "string", "description": "Optional child repo name"},
                "branch": {"type": "string", "description": "Optional child source branch"},
                "config": {"type": "object", "description": "Optional child run config"},
                "agent_runner_type": {
                    "type": "string",
                    "description": "Optional child runner type",
                },
                "agent_runner_config": {
                    "type": "object",
                    "description": "Optional child runner config",
                },
                "next_action_decision": {
                    "type": "string",
                    "enum": ["continue", "replan", "stop", "environment_blocked"],
                    "description": "Parent oversight decision that led to this child",
                },
            },
            "required": ["parent_run_id", "parent_slice_id", "routine_embedded"],
        },
    },
    {
        "name": "orchestrator_create_child_from_template",
        "description": (
            "Create an oversight child run by compiling a compact slice spec through a "
            "server-owned child workflow template."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_run_id": {"type": "string", "description": "Parent oversight run ID"},
                "slice_spec": {
                    "type": "object",
                    "description": "Compact child slice spec compiled by the server",
                    "properties": {
                        "template_id": {
                            "type": "string",
                            "enum": [
                                "bug_fix_with_regression_test",
                                "test_coverage_gap",
                                "frontend_behavior_fix",
                                "investigation_only",
                                "cleanup_refactor",
                                "environment_blocker_repro",
                            ],
                        },
                        "slice_id": {"type": "string"},
                        "goal": {"type": "string"},
                        "routine_id": {"type": "string"},
                        "title": {"type": "string"},
                        "target_inventory_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "allowed_paths": {"type": "array", "items": {"type": "string"}},
                        "expected_files_changed": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "verification_commands": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Commands the generated child should run through "
                                "scripts/run_child_evidence.py so logs and run.evidence.v1 "
                                "are produced together."
                            ),
                        },
                        "evidence_expectations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "stop_conditions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "real_execution_surface": {"type": "string"},
                        "real_frontend_path_required": {"type": "boolean"},
                        "notes": {"type": "string"},
                        "max_attempts": {"type": "integer", "minimum": 1, "maximum": 4},
                    },
                    "required": ["template_id", "slice_id", "goal"],
                },
                "repo_name": {"type": "string", "description": "Optional child repo name"},
                "branch": {"type": "string", "description": "Optional child source branch"},
                "config": {"type": "object", "description": "Optional child run config"},
                "agent_runner_type": {
                    "type": "string",
                    "description": "Optional child runner type",
                },
                "agent_runner_config": {
                    "type": "object",
                    "description": "Optional child runner config",
                },
                "next_action_decision": {
                    "type": "string",
                    "enum": ["continue", "replan", "stop", "environment_blocked"],
                    "description": "Parent oversight decision that led to this child",
                },
            },
            "required": ["parent_run_id", "slice_spec"],
        },
    },
    {
        "name": "orchestrator_list_child_runs",
        "description": "List child runs linked to an oversight parent run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_run_id": {"type": "string", "description": "Parent oversight run ID"},
            },
            "required": ["parent_run_id"],
        },
    },
    {
        "name": "orchestrator_accept_child_run",
        "description": "Merge an accepted child run into its parent run branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_run_id": {"type": "string", "description": "Parent run ID"},
                "child_run_id": {"type": "string", "description": "Child run ID to accept"},
            },
            "required": ["parent_run_id", "child_run_id"],
        },
    },
    {
        "name": "orchestrator_resolve_child_run",
        "description": "Reject or abandon a child run so the parent can continue iterating.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_run_id": {"type": "string", "description": "Parent run ID"},
                "child_run_id": {"type": "string", "description": "Child run ID to resolve"},
                "resolution": {
                    "type": "string",
                    "enum": ["reject", "abandon"],
                    "description": "Parent decision for this child",
                },
                "reason": {
                    "type": "string",
                    "description": "Audit reason for rejecting or abandoning this child",
                },
            },
            "required": ["parent_run_id", "child_run_id", "resolution", "reason"],
        },
    },
    {
        "name": "orchestrator_wait_for_run",
        "description": (
            "Wait for a run to complete, fail, or pause, then return its current status. "
            "If timed_out is true, do not poll repeatedly in the same LLM turn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID to observe"},
                "timeout_seconds": {
                    "type": "number",
                    "description": "Maximum seconds to wait, capped at 300",
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
    {
        "name": "orchestrator_get_parent_oversight",
        "description": "Return the persisted super-parent oversight snapshot for a parent run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Parent run ID to inspect"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "orchestrator_update_parent_oversight",
        "description": (
            "Persist parent-authored super-parent oversight facts such as target inventory, "
            "final validation, current understanding, and decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Parent run ID to update"},
                "current_understanding": {
                    "type": "object",
                    "description": "Optional current understanding payload",
                },
                "target_inventory": {
                    "type": "array",
                    "description": "Optional full replacement target inventory",
                    "items": {
                        "type": "object",
                        "properties": {
                            "schema_version": {
                                "type": "string",
                                "enum": ["super_parent.target_inventory.v1"],
                            },
                            "id": {"type": "string"},
                            "in_scope": {"type": "boolean"},
                            "resolved": {"type": "boolean"},
                        },
                        "required": ["id"],
                    },
                },
                "final_validation": {
                    "type": "object",
                    "description": "Optional integrated final validation marker",
                    "properties": {
                        "schema_version": {
                            "type": "string",
                            "enum": ["super_parent.final_validation.v1"],
                        },
                        "passed": {"type": "boolean"},
                        "integration_scope": {
                            "type": "string",
                            "enum": ["integrated", "final"],
                        },
                        "integrated_commit_sha": {"type": "string", "minLength": 7},
                        "report_path": {"type": "string", "minLength": 1},
                        "commands_run": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "command": {"type": "string"},
                                    "exit_code": {"type": "integer"},
                                    "stdout_excerpt": {"type": "string"},
                                    "stderr_excerpt": {"type": "string"},
                                },
                                "required": ["command", "exit_code"],
                            },
                        },
                        "evidence_files": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "passed",
                        "integrated_commit_sha",
                        "report_path",
                        "commands_run",
                        "evidence_files",
                    ],
                },
                "decisions": {
                    "type": "array",
                    "description": "Optional decision records to append",
                    "items": {"type": "object"},
                },
                "decision": {
                    "type": "object",
                    "description": "Optional single decision record to append",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "orchestrator_refresh_parent_oversight",
        "description": "Recompute and persist the super-parent oversight snapshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Parent run ID to refresh"},
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
        elif tool_name == "orchestrator_create_child_run":
            return await self._create_child_run(arguments)
        elif tool_name == "orchestrator_create_child_from_template":
            return await self._create_child_from_template(arguments)
        elif tool_name == "orchestrator_list_child_runs":
            return await self._list_child_runs(arguments)
        elif tool_name == "orchestrator_accept_child_run":
            return await self._accept_child_run(arguments)
        elif tool_name == "orchestrator_resolve_child_run":
            return await self._resolve_child_run(arguments)
        elif tool_name == "orchestrator_wait_for_run":
            return await self._wait_for_run(arguments)
        elif tool_name == "orchestrator_get_run_evidence":
            return await self._get_run_evidence(arguments)
        elif tool_name == "orchestrator_get_parent_oversight":
            return await self._get_parent_oversight(arguments)
        elif tool_name == "orchestrator_update_parent_oversight":
            return await self._update_parent_oversight(arguments)
        elif tool_name == "orchestrator_refresh_parent_oversight":
            return await self._refresh_parent_oversight(arguments)
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
            "requirement_id": requirement_id,
            "reason": reason,
            "message": "Requirement escalated. Run is paused for human review.",
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

    async def _create_child_run(self, args: dict[str, Any]) -> dict[str, Any]:
        parent_run_id: str = args["parent_run_id"]
        parent_slice_id: str = args["parent_slice_id"]
        routine_embedded: dict[str, Any] = args["routine_embedded"]
        decision: str = args.get("next_action_decision", "continue")
        if decision not in ("continue", "replan", "stop", "environment_blocked"):
            raise ValueError(
                "next_action_decision must be one of: continue, replan, stop, environment_blocked"
            )

        parent = await self._service.get_run(parent_run_id)
        routine_config = RoutineConfig.model_validate(routine_embedded)
        child = create_run_from_routine(
            routine=routine_config,
            repo_name=args.get("repo_name") or parent.repo_name,
            source_branch=_resolve_child_source_branch(parent, args.get("branch")),
            config=args.get("config") or {},
            routine_source=RoutineSource.EMBEDDED,
        )
        child.routine_embedded = routine_embedded

        agent_runner_type: str | None = args.get("agent_runner_type")
        if agent_runner_type:
            child.agent_runner_type = AgentRunnerType(agent_runner_type)
        else:
            child.agent_runner_type = parent.agent_runner_type
        child.agent_runner_config = args.get("agent_runner_config") or dict(
            parent.agent_runner_config
        )
        child.verifier_model = child.agent_runner_config.get("model") or parent.verifier_model

        child = await self._service.create_child_run(
            parent_run_id,
            child,
            parent_slice_id=parent_slice_id,
            next_action_decision=decision,
        )

        return {
            "parent_run_id": parent_run_id,
            "child_run_id": child.id,
            "parent_slice_id": child.parent_slice_id,
            "status": child.status.value,
            "start_enqueued": True,
        }

    async def _create_child_from_template(self, args: dict[str, Any]) -> dict[str, Any]:
        spec = ChildSliceSpec.model_validate(args["slice_spec"])
        routine_embedded = compile_child_routine_from_spec(spec)
        create_args = dict(args)
        create_args.pop("slice_spec")
        create_args["parent_slice_id"] = spec.slice_id
        create_args["routine_embedded"] = routine_embedded
        result = await self._create_child_run(create_args)
        result["template_id"] = spec.template_id
        result["routine_id"] = routine_embedded["id"]
        return result

    async def _list_child_runs(self, args: dict[str, Any]) -> dict[str, Any]:
        parent_run_id: str = args["parent_run_id"]
        children = await self._service.list_child_runs(parent_run_id)
        return {
            "parent_run_id": parent_run_id,
            "children": [
                {
                    "id": child.id,
                    "routine_id": child.routine_id,
                    "parent_slice_id": child.parent_slice_id,
                    "status": child.status.value,
                    "pause_reason": child.pause_reason,
                    "completed_at": format_utc_datetime(child.completed_at)
                    if child.completed_at
                    else None,
                }
                for child in children
            ],
        }

    async def _accept_child_run(self, args: dict[str, Any]) -> dict[str, Any]:
        parent_run_id: str = args["parent_run_id"]
        child_run_id: str = args["child_run_id"]
        result = await self._service.accept_child_run(parent_run_id, child_run_id)
        oversight_state = await self._service.get_parent_oversight(parent_run_id)
        return {
            "parent_run_id": parent_run_id,
            "child_run_id": child_run_id,
            "status": result.status,
            "merge_commit_sha": result.merge_commit_sha,
            "conflict_files": result.conflict_files,
            "conflict_count": result.conflict_count,
            "oversight_state": oversight_state,
        }

    async def _resolve_child_run(self, args: dict[str, Any]) -> dict[str, Any]:
        parent_run_id: str = args["parent_run_id"]
        child_run_id: str = args["child_run_id"]
        resolution: str = args["resolution"]
        if resolution not in ("reject", "abandon"):
            raise ValueError("resolution must be one of: reject, abandon")
        resolution_literal: Literal["reject", "abandon"] = (
            "reject" if resolution == "reject" else "abandon"
        )
        reason = str(args["reason"]).strip()
        result = await self._service.resolve_child_run(
            parent_run_id,
            child_run_id,
            resolution=resolution_literal,
            reason=reason,
        )
        oversight_state = await self._service.get_parent_oversight(parent_run_id)
        return {
            "parent_run_id": parent_run_id,
            "child_run_id": child_run_id,
            "resolution": result.resolution,
            "reason": result.reason,
            "resolved_at": format_utc_datetime(result.resolved_at),
            "oversight_state": oversight_state,
        }

    async def _wait_for_run(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        requested_timeout_seconds = float(args.get("timeout_seconds", 0))
        timeout_seconds = min(requested_timeout_seconds, 300.0)
        initial_run = await self._service.get_run(run_id)
        parent_run_id = initial_run.parent_run_id
        if parent_run_id:
            await self._service.record_child_wait_observation(
                parent_run_id,
                run_id,
                observed_status=initial_run.status,
                phase="started",
                timeout_seconds=timeout_seconds,
            )
        run = await self._service.wait_for_run_terminal(run_id, timeout_seconds)
        if parent_run_id:
            await self._service.record_child_wait_observation(
                parent_run_id,
                run_id,
                observed_status=run.status,
                phase="observed",
                timeout_seconds=timeout_seconds,
            )
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

    async def _get_parent_oversight(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        oversight_state = await self._service.get_parent_oversight(run_id)
        return {"run_id": run_id, "oversight_state": oversight_state}

    async def _update_parent_oversight(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        decisions: list[dict[str, Any]] | None = None
        if isinstance(args.get("decisions"), list):
            decisions = [
                dict(cast(Mapping[str, Any], item))
                for item in args["decisions"]
                if isinstance(item, Mapping)
            ]
        if isinstance(args.get("decision"), Mapping):
            decisions = [*(decisions or []), dict(cast(Mapping[str, Any], args["decision"]))]

        current_understanding: dict[str, Any] | None = None
        if isinstance(args.get("current_understanding"), Mapping):
            current_understanding = dict(cast(Mapping[str, Any], args["current_understanding"]))

        target_inventory: list[dict[str, Any]] | None = None
        if isinstance(args.get("target_inventory"), list):
            target_inventory = [
                dict(cast(Mapping[str, Any], item))
                for item in args["target_inventory"]
                if isinstance(item, Mapping)
            ]

        final_validation: dict[str, Any] | None = None
        if isinstance(args.get("final_validation"), Mapping):
            final_validation = dict(cast(Mapping[str, Any], args["final_validation"]))

        run = await self._service.update_parent_oversight(
            run_id,
            current_understanding=current_understanding,
            target_inventory=target_inventory,
            final_validation=final_validation,
            decisions=decisions,
        )
        return {"run_id": run.id, "oversight_state": run.oversight_state}

    async def _refresh_parent_oversight(self, args: dict[str, Any]) -> dict[str, Any]:
        run_id: str = args["run_id"]
        run = await self._service.refresh_parent_oversight(run_id)
        return {"run_id": run.id, "oversight_state": run.oversight_state}
