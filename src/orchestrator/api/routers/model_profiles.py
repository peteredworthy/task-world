"""Model profiles API endpoints."""

from fastapi import APIRouter

from orchestrator.api.schemas.model_profiles import ModelProfileSchema
from orchestrator.config.enums import ModelProfile

router = APIRouter(prefix="/api/model-profiles", tags=["model-profiles"])

_PROFILE_DESCRIPTIONS: dict[ModelProfile, str] = {
    ModelProfile.ARCHITECT: "Planning and design tasks: system architecture, technical specs, and high-level design decisions.",
    ModelProfile.DESIGNER: "UI/UX tasks: interface design, user experience, and visual layout decisions.",
    ModelProfile.CODER: "Implementation tasks: writing, refactoring, and debugging code.",
    ModelProfile.SUMMARIZER: "Documentation and context tasks: summarizing content, writing docs, and distilling context.",
}


@router.get("", response_model=list[ModelProfileSchema])
async def list_model_profiles() -> list[ModelProfileSchema]:
    """List all available model profiles with descriptions."""
    return [
        ModelProfileSchema(name=profile, description=_PROFILE_DESCRIPTIONS[profile])
        for profile in ModelProfile
    ]
