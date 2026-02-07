"""MCP tool definitions for clarification requests.

Provides tools for agents to request clarification from humans during
task execution.
"""

from typing import Any

CLARIFICATION_TOOL: dict[str, Any] = {
    "name": "orchestrator_request_clarification",
    "description": (
        "Request clarification from the human. "
        "The task will pause until the human answers. "
        "Answers will be appended to the clarifications artifact file."
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
                        "question": {"type": "string", "description": "The question text"},
                        "context": {
                            "type": "string",
                            "description": "Why this clarification is needed",
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-4 suggested answers (user can also provide custom)",
                            "minItems": 2,
                            "maxItems": 4,
                        },
                    },
                    "required": ["question", "context", "options"],
                },
            },
        },
        "required": ["run_id", "task_id", "questions"],
    },
}
