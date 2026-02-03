"""MCP tool definitions and handler for orchestrator operations.

ToolHandler dispatches tool calls to WorkflowService methods.
It is tested independently of server transport.
"""

from __future__ import annotations

from typing import Any

from orchestrator.config.enums import ChecklistStatus
from orchestrator.workflow.service import WorkflowService

# JSON schemas for the 4 orchestrator MCP tools
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
]


class ToolHandler:
    """Dispatches MCP tool calls to WorkflowService methods."""

    def __init__(self, service: WorkflowService) -> None:
        self._service = service

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
