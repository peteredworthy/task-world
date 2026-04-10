"""Context assembly from artifacts for multi-artifact task context injection."""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orchestrator.config.models import ContextSource
from orchestrator.workflow.artifacts import ArtifactRegistry

if TYPE_CHECKING:
    from orchestrator.workflow.agent.summary_cache import SummaryCache


class ContextError(Exception):
    """Error during context building."""

    pass


class TaskContextBuilder:
    """Build task context from multiple artifacts."""

    def __init__(
        self,
        artifact_registry: ArtifactRegistry,
        worktree_path: Path | None = None,
    ) -> None:
        """
        Initialize context builder.

        Args:
            artifact_registry: Registry to fetch artifacts from
            worktree_path: Path to worktree for filesystem fallback
        """
        self._registry = artifact_registry
        self._worktree = worktree_path

    async def build_context(
        self,
        run_id: str,
        context_sources: list[ContextSource],
        variables: dict[str, Any],
        total_token_limit: int = 8000,
        summary_cache: "SummaryCache | None" = None,
    ) -> dict[str, str]:
        """
        Build context dict from artifact sources.

        Args:
            run_id: Run identifier
            context_sources: List of artifact sources to load
            variables: Variables for path substitution
            total_token_limit: Total token budget for all artifacts

        Returns:
            Dict mapping as_name -> content

        Raises:
            ContextError: If a required artifact is not found
        """
        context: dict[str, str] = {}
        remaining_tokens = total_token_limit

        for source in context_sources:
            # Resolve path with variables
            path = resolve_variables(source.artifact, variables)

            # Get artifact content
            content = self._get_artifact_content(run_id, path)

            if content is None:
                if source.required:
                    raise ContextError(f"Required artifact not found: {path}")
                continue

            # Extract section if specified
            if source.section:
                content = extract_section(content, source.section)

            # Summarize if requested
            if source.summarize and summary_cache is not None:
                content = await summary_cache.get_or_generate(
                    artifact_path=path,
                    content=content,
                    model=source.summarize_model,
                    critical=source.critical,
                )

            # Apply token limit
            limit = min(
                source.max_tokens or remaining_tokens,
                remaining_tokens,
            )
            content = truncate_to_tokens(content, limit)

            remaining_tokens -= count_tokens(content)
            if source.as_name is not None:
                context[source.as_name] = content

            if remaining_tokens <= 0:
                break  # No more budget

        return context

    def _get_artifact_content(self, run_id: str, path: str) -> str | None:
        """
        Get content from registry or filesystem.

        Args:
            run_id: Run identifier
            path: Relative path to artifact

        Returns:
            Content as string, or None if not found
        """
        # First check registry
        artifact = self._registry.get_latest(run_id, path)
        if artifact:
            # For now, fall through to filesystem
            # In a full implementation, we'd read from the artifact's recorded location
            pass

        # Fall back to filesystem
        if self._worktree:
            full_path = self._worktree / path
            if full_path.exists():
                return full_path.read_text()

        return None


def resolve_variables(template: str, variables: dict[str, Any]) -> str:
    """
    Resolve {{variable}} placeholders in a template string.

    Args:
        template: Template string with {{key}} placeholders
        variables: Dict mapping keys to values

    Returns:
        Resolved string
    """
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


def extract_section(content: str, section: str) -> str:
    """
    Extract a specific section from markdown content.

    Looks for a heading matching the section name (case-insensitive)
    and returns content until the next heading of the same or higher level.

    Args:
        content: Markdown content
        section: Section name to extract (without # prefix)

    Returns:
        Section content, or empty string if not found
    """
    lines = content.split("\n")
    section_lower = section.lower()
    in_section = False
    section_level = 0
    result_lines: list[str] = []

    for line in lines:
        # Check if this is a heading
        heading_match = re.match(r"^(#+)\s+(.+)$", line)

        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip().lower()

            if not in_section:
                # Check if this is our target section
                if heading_text == section_lower:
                    in_section = True
                    section_level = level
                    continue  # Don't include the heading itself
            else:
                # Check if this ends our section (same or higher level)
                if level <= section_level:
                    break

        if in_section:
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def truncate_to_tokens(content: str, limit: int) -> str:
    """
    Truncate content to approximately fit within token limit.

    Uses a simple heuristic of ~4 characters per token.

    Args:
        content: Content to truncate
        limit: Maximum tokens

    Returns:
        Truncated content
    """
    if limit <= 0:
        return ""

    char_limit = limit * 4
    if len(content) <= char_limit:
        return content

    # Truncate at character boundary and add ellipsis
    return content[:char_limit] + "\n\n[...truncated]"


def count_tokens(content: str) -> int:
    """
    Estimate token count for content.

    Uses a simple heuristic of ~4 characters per token.

    Args:
        content: Content to count

    Returns:
        Estimated token count
    """
    return len(content) // 4
