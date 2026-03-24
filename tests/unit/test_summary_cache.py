"""Tests for SummaryCache — no mocks, patch, or MagicMock.

Uses test-specific subclasses to control API responses via dependency injection.
"""

from pathlib import Path

import pytest

from orchestrator.workflow.artifacts import ArtifactRegistry
from orchestrator.config.models import ContextSource
from orchestrator.workflow.context_builder import TaskContextBuilder
from orchestrator.workflow.summary_cache import SummaryCache


# ---------------------------------------------------------------------------
# Test-specific implementations (no mocking)
# ---------------------------------------------------------------------------


class StubSummaryCache(SummaryCache):
    """SummaryCache that returns pre-configured responses from _do_api_call.

    Accepts a list of responses; each call to _do_api_call consumes the next
    entry. None entries simulate API failures (empty / error response).
    """

    def __init__(self, responses: list[str | None]) -> None:
        super().__init__()
        self._responses = list(responses)
        self._call_count = 0
        self._call_messages: list[list[dict[str, str]]] = []

    async def _do_api_call(self, model: str, messages: list[dict[str, str]]) -> str | None:
        self._call_messages.append(messages)
        if self._call_count < len(self._responses):
            result = self._responses[self._call_count]
        else:
            result = None
        self._call_count += 1
        return result


# ---------------------------------------------------------------------------
# Test 1: Summary generation produces shorter output than original
# ---------------------------------------------------------------------------


class TestSummaryGenerationShorter:
    @pytest.mark.asyncio
    async def test_summary_is_shorter_than_original(self) -> None:
        """Summary produced by get_or_generate is shorter than the original content."""
        original = "This is a very long document with a lot of content. " * 20
        short_summary = "Short summary of the document."

        cache = StubSummaryCache(responses=[short_summary])
        result = await cache.get_or_generate(
            artifact_path="doc.md",
            content=original,
        )

        assert result == short_summary
        assert len(result) < len(original)

    @pytest.mark.asyncio
    async def test_summary_stored_in_cache_after_generation(self) -> None:
        """After generation, the summary is retrievable from cache."""
        original = "Long content here. " * 10
        summary = "Concise summary."

        cache = StubSummaryCache(responses=[summary])
        result = await cache.get_or_generate(artifact_path="a.md", content=original)

        assert result == summary
        cached = cache.get_cached("a.md", original)
        assert cached == summary


# ---------------------------------------------------------------------------
# Test 2: Cache hit returns cached summary without calling model
# ---------------------------------------------------------------------------


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_second_call_returns_cached_without_api_call(self) -> None:
        """Second get_or_generate with same content uses cache, skips API."""
        original = "Content to summarize."
        summary = "Brief summary."

        cache = StubSummaryCache(responses=[summary, "should-not-be-returned"])
        # First call — generates and caches
        first = await cache.get_or_generate(artifact_path="f.md", content=original)
        assert first == summary
        assert cache._call_count == 1

        # Second call — should hit cache, NOT call _do_api_call again
        second = await cache.get_or_generate(artifact_path="f.md", content=original)
        assert second == summary
        assert cache._call_count == 1  # no additional API call

    @pytest.mark.asyncio
    async def test_different_content_different_cache_entry(self) -> None:
        """Different content for the same path gets its own cache entry."""
        cache = StubSummaryCache(responses=["summary-a", "summary-b"])

        result_a = await cache.get_or_generate(artifact_path="f.md", content="Content A.")
        result_b = await cache.get_or_generate(artifact_path="f.md", content="Content B.")

        assert result_a == "summary-a"
        assert result_b == "summary-b"
        assert cache._call_count == 2

    @pytest.mark.asyncio
    async def test_store_then_get_cached_bypasses_generation(self) -> None:
        """Manually storing a summary means get_or_generate never calls the model."""
        cache = StubSummaryCache(responses=["should-never-be-called"])
        cache.store("artifact.md", "some content", "manually stored summary")

        result = await cache.get_or_generate(artifact_path="artifact.md", content="some content")

        assert result == "manually stored summary"
        assert cache._call_count == 0


# ---------------------------------------------------------------------------
# Test 3: Missing critical aspect triggers re-summarization
# ---------------------------------------------------------------------------


class TestCriticalAspectRetry:
    def test_check_critical_aspects_passes_when_words_present(self) -> None:
        """_check_critical_aspects returns True when all long critical words are present."""
        cache = SummaryCache()
        summary = "The authentication token expiry mechanism is described here."
        assert cache._check_critical_aspects(summary, "token expiry") is True

    def test_check_critical_aspects_fails_when_word_missing(self) -> None:
        """_check_critical_aspects returns False when a long critical word is missing."""
        cache = SummaryCache()
        summary = "The login mechanism is described here."
        assert cache._check_critical_aspects(summary, "token expiry") is False

    def test_check_critical_aspects_ignores_short_words(self) -> None:
        """Short words (<=4 chars) in critical are ignored during the check."""
        cache = SummaryCache()
        # 'the' and 'an' are short words, should be ignored
        summary = "Some random content."
        assert cache._check_critical_aspects(summary, "the an or") is True

    @pytest.mark.asyncio
    async def test_missing_critical_triggers_second_api_call(self) -> None:
        """When first summary lacks critical aspect, a second API call is made."""
        # First response: missing the critical word 'authentication'
        # Second response: includes 'authentication'
        cache = StubSummaryCache(
            responses=[
                "The login system is working.",  # missing 'authentication'
                "The authentication system is fully described.",  # includes it
            ]
        )
        result = await cache.get_or_generate(
            artifact_path="auth.md",
            content="Long content about authentication mechanisms. " * 10,
            critical="authentication",
        )

        assert cache._call_count == 2
        assert "authentication" in result

    @pytest.mark.asyncio
    async def test_retry_message_emphasizes_critical_aspect(self) -> None:
        """The retry prompt explicitly mentions the critical aspect."""
        cache = StubSummaryCache(
            responses=[
                "Generic summary without the keyword.",
                "Summary with importantkeyword included.",
            ]
        )
        await cache.get_or_generate(
            artifact_path="doc.md",
            content="Content. " * 20,
            critical="importantkeyword",
        )

        assert cache._call_count == 2
        # Second message should explicitly include the critical description
        retry_message = cache._call_messages[1][0]["content"]
        assert "importantkeyword" in retry_message

    @pytest.mark.asyncio
    async def test_no_retry_when_critical_aspect_present(self) -> None:
        """When first summary already includes critical aspect, no retry occurs."""
        cache = StubSummaryCache(
            responses=[
                "The authentication system is fully covered.",
                "Should never be called.",
            ]
        )
        result = await cache.get_or_generate(
            artifact_path="doc.md",
            content="Content about authentication. " * 5,
            critical="authentication",
        )

        assert cache._call_count == 1
        assert result == "The authentication system is fully covered."

    @pytest.mark.asyncio
    async def test_max_two_iterations_even_if_critical_still_missing(self) -> None:
        """Re-summarization stops after 2 iterations even if critical still missing."""
        # Both responses missing the critical aspect
        cache = StubSummaryCache(
            responses=[
                "Generic summary one.",
                "Generic summary two.",
            ]
        )
        result = await cache.get_or_generate(
            artifact_path="doc.md",
            content="Content. " * 20,
            critical="authentication",
        )

        # Should stop after 2 iterations and return whatever we have
        assert cache._call_count == 2
        assert result is not None  # Returns last summary, not None


# ---------------------------------------------------------------------------
# Test 4: Model failure falls back to full content
# ---------------------------------------------------------------------------


class TestFallbackOnFailure:
    @pytest.mark.asyncio
    async def test_api_failure_returns_full_content(self) -> None:
        """When _do_api_call returns None, get_or_generate falls back to full content."""
        original = "Full original content that should be returned on failure."
        cache = StubSummaryCache(responses=[None])  # API fails

        result = await cache.get_or_generate(artifact_path="fail.md", content=original)

        assert result == original

    @pytest.mark.asyncio
    async def test_empty_response_treated_as_failure(self) -> None:
        """Empty string response from API is treated like failure — falls back to full content."""
        original = "Original content."
        cache = StubSummaryCache(responses=[""])  # empty response

        result = await cache.get_or_generate(artifact_path="fail.md", content=original)

        assert result == original

    @pytest.mark.asyncio
    async def test_fallback_not_stored_in_cache(self) -> None:
        """When fallback occurs (failure), the full content is NOT stored as a cached summary."""
        original = "Original content."
        cache = StubSummaryCache(responses=[None])

        await cache.get_or_generate(artifact_path="fail.md", content=original)

        # Nothing stored in cache — next call will hit API again
        cached = cache.get_cached("fail.md", original)
        assert cached is None

    @pytest.mark.asyncio
    async def test_no_responses_falls_back_to_full_content(self) -> None:
        """When response list is exhausted, falls back to full content."""
        original = "Content when no responses configured."
        cache = StubSummaryCache(responses=[])  # empty response list

        result = await cache.get_or_generate(artifact_path="empty.md", content=original)

        assert result == original


# ---------------------------------------------------------------------------
# Test 5: End-to-end prompt assembly with summarized context
# ---------------------------------------------------------------------------


class TestEndToEndWithSummarizedContext:
    @pytest.mark.asyncio
    async def test_context_builder_uses_summary_cache(self, tmp_path: Path) -> None:
        """TaskContextBuilder passes artifact content through SummaryCache when summarize=True."""
        long_content = "Detailed implementation notes. " * 50
        summary_text = "Short summary of implementation notes."

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "notes.md").write_text(long_content)

        registry = ArtifactRegistry()
        registry.register("run-1", "S-01", "T-01", "notes.md", long_content.encode())

        cache = StubSummaryCache(responses=[summary_text])
        builder = TaskContextBuilder(registry, worktree)

        sources = [
            ContextSource.model_validate(
                {"artifact": "notes.md", "as": "notes", "required": True, "summarize": True}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
            summary_cache=cache,
        )

        assert "notes" in context
        assert context["notes"] == summary_text
        assert cache._call_count == 1

    @pytest.mark.asyncio
    async def test_context_builder_without_cache_skips_summarization(self, tmp_path: Path) -> None:
        """When no summary_cache is provided, summarize=True is ignored."""
        content = "Full content that should appear unsummarized."
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "doc.md").write_text(content)

        registry = ArtifactRegistry()
        registry.register("run-1", "S-01", "T-01", "doc.md", content.encode())

        builder = TaskContextBuilder(registry, worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "doc.md", "as": "doc", "required": True, "summarize": True}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
            summary_cache=None,  # No cache provided
        )

        # Full content used when no summary_cache
        assert context["doc"] == content

    @pytest.mark.asyncio
    async def test_context_builder_cache_hit_on_second_build(self, tmp_path: Path) -> None:
        """Repeated build_context calls for same artifact use cache on second call."""
        content = "Artifact content. " * 30
        summary_text = "Summarized artifact."

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "artifact.md").write_text(content)

        registry = ArtifactRegistry()
        registry.register("run-1", "S-01", "T-01", "artifact.md", content.encode())

        cache = StubSummaryCache(responses=[summary_text])
        builder = TaskContextBuilder(registry, worktree)

        sources = [
            ContextSource.model_validate(
                {"artifact": "artifact.md", "as": "art", "required": True, "summarize": True}
            ),
        ]

        # First call — API hit
        ctx1 = await builder.build_context(
            run_id="run-1", context_sources=sources, variables={}, summary_cache=cache
        )
        # Second call — should use cache
        ctx2 = await builder.build_context(
            run_id="run-1", context_sources=sources, variables={}, summary_cache=cache
        )

        assert ctx1["art"] == summary_text
        assert ctx2["art"] == summary_text
        assert cache._call_count == 1  # Only one API call total

    @pytest.mark.asyncio
    async def test_context_builder_fallback_when_summarization_fails(self, tmp_path: Path) -> None:
        """When summarization fails, full content is injected into context."""
        content = "Full original content for the artifact."
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "fail.md").write_text(content)

        registry = ArtifactRegistry()
        registry.register("run-1", "S-01", "T-01", "fail.md", content.encode())

        cache = StubSummaryCache(responses=[None])  # API failure
        builder = TaskContextBuilder(registry, worktree)

        sources = [
            ContextSource.model_validate(
                {"artifact": "fail.md", "as": "doc", "required": True, "summarize": True}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            summary_cache=cache,
        )

        # Fallback to full content
        assert context["doc"] == content

    @pytest.mark.asyncio
    async def test_context_builder_with_critical_aspect(self, tmp_path: Path) -> None:
        """Critical aspect is passed through to summary cache correctly."""
        content = "Document about authentication and token management. " * 10
        summary = "Authentication and token expiry documented."

        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "auth.md").write_text(content)

        registry = ArtifactRegistry()
        registry.register("run-1", "S-01", "T-01", "auth.md", content.encode())

        cache = StubSummaryCache(responses=[summary])
        builder = TaskContextBuilder(registry, worktree)

        sources = [
            ContextSource.model_validate(
                {
                    "artifact": "auth.md",
                    "as": "auth_doc",
                    "required": True,
                    "summarize": True,
                    "critical": "authentication token",
                }
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            summary_cache=cache,
        )

        assert context["auth_doc"] == summary
        # The prompt sent to the API should mention the critical aspect
        assert "authentication" in cache._call_messages[0][0]["content"]
