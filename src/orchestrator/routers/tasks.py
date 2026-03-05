"""Re-export shim: the tasks router lives in orchestrator.api.routers.tasks."""

from orchestrator.api.routers.tasks import router

__all__ = ["router"]
