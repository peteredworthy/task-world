"""Summary cache for artifact content summarization.

Caches summaries keyed by (artifact_path, content_hash) for the duration of a run.
Uses a configurable model to generate summaries, with critical-aspect verification
and fallback to full content on failure.
"""

import hashlib
import logging

from orchestrator.config.models import DEFAULT_SUMMARIZE_MODEL

logger = logging.getLogger(__name__)


class SummaryCache:
    """Cache summaries keyed by (artifact_path, content_hash).

    Summaries are generated using a configurable model and cached for the
    lifetime of the run. If critical aspects are specified, the summary is
    checked and re-generated (up to 2 iterations) if they are missing.
    Falls back to full content on model failure.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], str] = {}

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def get_cached(self, artifact_path: str, content: str) -> str | None:
        """Return cached summary if available for this content."""
        key = (artifact_path, self._content_hash(content))
        return self._cache.get(key)

    def store(self, artifact_path: str, content: str, summary: str) -> None:
        """Store a summary in the cache."""
        key = (artifact_path, self._content_hash(content))
        self._cache[key] = summary

    def _check_critical_aspects(self, summary: str, critical: str) -> bool:
        """Check whether the summary preserves the critical aspects.

        Uses a simple heuristic: each word from the critical description
        that is longer than 4 characters should appear somewhere in the summary.
        This is intentionally lightweight to avoid another API call.
        """
        critical_words = [w.lower() for w in critical.split() if len(w) > 4]
        summary_lower = summary.lower()
        return all(word in summary_lower for word in critical_words)

    async def get_or_generate(
        self,
        artifact_path: str,
        content: str,
        model: str | None = None,
        critical: str | None = None,
    ) -> str:
        """Get cached summary or generate a new one.

        Args:
            artifact_path: Path of the artifact (used as cache key).
            content: Full artifact content to summarize.
            model: Model to use for summarization (defaults to DEFAULT_SUMMARIZE_MODEL).
            critical: Description of critical aspects that must appear in summary.

        Returns:
            Summary string, or full content if summarization fails.
        """
        cached = self.get_cached(artifact_path, content)
        if cached is not None:
            return cached

        effective_model = model or DEFAULT_SUMMARIZE_MODEL
        summary = await self._generate_summary(content, effective_model, critical)
        if summary is not None:
            self.store(artifact_path, content, summary)
            return summary

        # Fallback: return full content
        logger.warning("Summarization failed for %s, falling back to full content", artifact_path)
        return content

    async def _generate_summary(
        self,
        content: str,
        model: str,
        critical: str | None,
    ) -> str | None:
        """Generate a summary using the Anthropic API.

        Attempts up to 2 iterations if critical aspects are missing from the summary.
        Returns None on API failure.
        """
        try:
            import anthropic  # lazy import — not all deployments need this
        except ImportError:
            logger.warning("anthropic package not available; cannot summarize")
            return None

        client = anthropic.AsyncAnthropic()

        base_prompt = (
            "Summarize the following content concisely, preserving all key information "
            "that would be useful to a developer implementing a software task."
        )
        if critical:
            base_prompt += f" Make sure to preserve: {critical}."

        messages: list[dict[str, str]] = [
            {"role": "user", "content": f"{base_prompt}\n\n---\n{content}"},
        ]

        max_iterations = 2
        last_summary: str | None = None

        for iteration in range(max_iterations):
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=1024,
                    messages=messages,  # type: ignore[arg-type]
                )
                text_blocks = [b for b in response.content if b.type == "text"]
                summary: str | None = text_blocks[0].text if text_blocks else None  # type: ignore[union-attr]
                if not summary:
                    logger.warning("Empty summary returned by model %s", model)
                    return last_summary

                last_summary = summary

                # Check critical aspects
                if critical and not self._check_critical_aspects(summary, critical):
                    if iteration < max_iterations - 1:
                        # Re-request with explicit preservation instruction
                        logger.debug(
                            "Summary missing critical aspects on iteration %d, retrying", iteration
                        )
                        messages = [
                            {
                                "role": "user",
                                "content": (
                                    f"Summarize the following content concisely. "
                                    f"You MUST explicitly include information about: {critical}. "
                                    f"This is critical — do not omit it.\n\n---\n{content}"
                                ),
                            }
                        ]
                        continue

                return summary

            except Exception as exc:
                logger.warning("Summarization API call failed: %s", exc)
                return last_summary

        return last_summary
