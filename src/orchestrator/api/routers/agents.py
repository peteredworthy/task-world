"""Agent discovery API endpoints."""

from fastapi import APIRouter, Request

from orchestrator.agents.detector import ToolDetector
from orchestrator.agents.types import AgentOption

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentOption])
async def list_agents(request: Request) -> list[AgentOption]:
    """List available agent backends."""
    detector: ToolDetector = request.app.state.tool_detector
    return await detector.detect_all()
