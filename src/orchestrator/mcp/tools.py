"""MCP tool definitions and handler for orchestrator operations.

ToolHandler dispatches tool calls to WorkflowService methods.
It is tested independently of server transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.config.enums import ChecklistStatus
from orchestrator.mcp.clarification_tools import CLARIFICATION_TOOL
from orchestrator.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.repos.errors import RepoNotFoundError
from orchestrator.workflow.clarifications import ClarificationQuestion
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
    CLARIFICATION_TOOL,
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
        elif tool_name == "orchestrator_request_clarification":
            return await self._request_clarification(arguments)
        elif tool_name == "orchestrator_list_repos":
            return await self._list_repos(arguments)
        elif tool_name == "orchestrator_list_branches":
            return await self._list_branches(arguments)
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
        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        req_id: str = args["req_id"]
        grade: str = args["grade"]
        grade_reason: str | None = args.get("grade_reason")

        item = await self._service.set_grade(run_id, task_id, req_id, grade, grade_reason)
        return {
            "req_id": item.req_id,
            "grade": item.grade,
            "grade_reason": item.grade_reason,
        }

    async def _request_clarification(self, args: dict[str, Any]) -> dict[str, Any]:
        import uuid

        run_id: str = args["run_id"]
        task_id: str = args["task_id"]
        questions_data: list[dict[str, Any]] = args["questions"]

        # Convert dict questions to ClarificationQuestion objects
        questions = [
            ClarificationQuestion(
                id=str(uuid.uuid4()),
                question=q["question"],
                context=q["context"],
                options=q["options"],
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
                }
                for q in request.questions
            ],
            "created_at": request.created_at.isoformat(),
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
