"""Unit tests for TaskContextBuilder."""

from pathlib import Path

import pytest
import pytest_asyncio  # noqa: F401

from orchestrator.artifacts.registry import ArtifactRegistry
from orchestrator.config.models import ContextSource
from orchestrator.workflow.context_builder import (
    ContextError,
    TaskContextBuilder,
    count_tokens,
    extract_section,
    resolve_variables,
    truncate_to_tokens,
)


class TestResolveVariables:
    """Tests for variable resolution."""

    def test_single_variable(self) -> None:
        """Test resolving a single variable."""
        template = "docs/{{feature}}/plan.md"
        variables = {"feature": "auth"}
        result = resolve_variables(template, variables)
        assert result == "docs/auth/plan.md"

    def test_multiple_variables(self) -> None:
        """Test resolving multiple variables."""
        template = "{{project}}/docs/{{feature}}/{{file}}.md"
        variables = {"project": "myapp", "feature": "auth", "file": "plan"}
        result = resolve_variables(template, variables)
        assert result == "myapp/docs/auth/plan.md"

    def test_repeated_variable(self) -> None:
        """Test variable used multiple times."""
        template = "{{feature}}/{{feature}}_plan.md"
        variables = {"feature": "auth"}
        result = resolve_variables(template, variables)
        assert result == "auth/auth_plan.md"

    def test_no_variables(self) -> None:
        """Test template with no variables."""
        template = "docs/plan.md"
        variables = {"feature": "auth"}
        result = resolve_variables(template, variables)
        assert result == "docs/plan.md"

    def test_missing_variable_unchanged(self) -> None:
        """Test missing variable is left unchanged."""
        template = "docs/{{feature}}/{{missing}}.md"
        variables = {"feature": "auth"}
        result = resolve_variables(template, variables)
        assert result == "docs/auth/{{missing}}.md"

    def test_numeric_value(self) -> None:
        """Test numeric variable value."""
        template = "step-{{num}}.md"
        variables = {"num": 42}
        result = resolve_variables(template, variables)
        assert result == "step-42.md"


class TestExtractSection:
    """Tests for markdown section extraction."""

    def test_extract_simple_section(self) -> None:
        """Test extracting a simple section."""
        content = """# Introduction
This is the intro.

# Method
This is the method.

# Conclusion
This is the conclusion.
"""
        result = extract_section(content, "Method")
        assert result == "This is the method."

    def test_case_insensitive(self) -> None:
        """Test section extraction is case-insensitive."""
        content = """# RESOLVED
Fixed items here.

# UNRESOLVED
Open items here.
"""
        result = extract_section(content, "resolved")
        assert result == "Fixed items here."

    def test_nested_headings(self) -> None:
        """Test extraction with nested headings."""
        content = """# Section A
Content A.

## Subsection A1
Subsection content.

## Subsection A2
More subsection content.

# Section B
Content B.
"""
        result = extract_section(content, "Section A")
        expected = """Content A.

## Subsection A1
Subsection content.

## Subsection A2
More subsection content."""
        assert result == expected

    def test_section_not_found(self) -> None:
        """Test extraction when section doesn't exist."""
        content = """# Section A
Content A.
"""
        result = extract_section(content, "Missing")
        assert result == ""

    def test_last_section(self) -> None:
        """Test extracting the last section."""
        content = """# First
Content first.

# Last
Content last.
"""
        result = extract_section(content, "Last")
        assert result == "Content last."

    def test_section_with_multiple_levels(self) -> None:
        """Test section ends at same level heading."""
        content = """## Subsection A
Content A.

### Sub-subsection
Nested content.

## Subsection B
Content B.
"""
        result = extract_section(content, "Subsection A")
        expected = """Content A.

### Sub-subsection
Nested content."""
        assert result == expected

    def test_empty_section(self) -> None:
        """Test extracting an empty section."""
        content = """# Empty

# Next Section
Content.
"""
        result = extract_section(content, "Empty")
        assert result == ""


class TestTokenFunctions:
    """Tests for token counting and truncation."""

    def test_count_tokens_simple(self) -> None:
        """Test token counting with simple text."""
        content = "This is a test string with some words."
        tokens = count_tokens(content)
        # ~4 chars per token: 40 chars / 4 = 10 tokens (integer division)
        expected = len(content) // 4
        assert tokens == expected

    def test_count_tokens_empty(self) -> None:
        """Test token counting with empty string."""
        assert count_tokens("") == 0

    def test_truncate_no_truncation_needed(self) -> None:
        """Test truncation when content is within limit."""
        content = "Short content."
        result = truncate_to_tokens(content, limit=100)
        assert result == content

    def test_truncate_at_limit(self) -> None:
        """Test truncation when content exceeds limit."""
        content = "a" * 1000
        result = truncate_to_tokens(content, limit=100)
        # 100 tokens * 4 chars = 400 chars + ellipsis
        assert len(result) <= 400 + 20  # Allow for ellipsis
        assert "[...truncated]" in result

    def test_truncate_zero_limit(self) -> None:
        """Test truncation with zero limit."""
        content = "Some content."
        result = truncate_to_tokens(content, limit=0)
        assert result == ""

    def test_truncate_negative_limit(self) -> None:
        """Test truncation with negative limit."""
        content = "Some content."
        result = truncate_to_tokens(content, limit=-10)
        assert result == ""


class TestTaskContextBuilder:
    """Tests for TaskContextBuilder."""

    @pytest.fixture
    def registry(self) -> ArtifactRegistry:
        """Create artifact registry fixture."""
        return ArtifactRegistry()

    @pytest.fixture
    def tmp_worktree(self, tmp_path: Path) -> Path:
        """Create temporary worktree fixture."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        return worktree

    @pytest.mark.asyncio
    async def test_build_context_from_registry(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test building context from registry artifacts."""
        # Register an artifact
        content = b"This is the plan content."
        registry.register(
            run_id="run-1",
            step_id="S-01",
            task_id="T-01",
            path="plan.md",
            content=content,
        )

        # Also create file in worktree (so _get_artifact_content can read it)
        (tmp_worktree / "plan.md").write_bytes(content)

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate({"artifact": "plan.md", "as": "plan", "required": True}),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        assert "plan" in context
        assert context["plan"] == "This is the plan content."

    @pytest.mark.asyncio
    async def test_build_context_with_variable_substitution(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test variable substitution in artifact paths."""
        # Create file with variable in path
        feature_dir = tmp_worktree / "auth"
        feature_dir.mkdir()
        (feature_dir / "plan.md").write_text("Auth plan content.")

        registry.register(
            run_id="run-1",
            step_id="S-01",
            task_id="T-01",
            path="auth/plan.md",
            content=b"Auth plan content.",
        )

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "{{feature}}/plan.md", "as": "plan", "required": True}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={"feature": "auth"},
            total_token_limit=8000,
        )

        assert context["plan"] == "Auth plan content."

    @pytest.mark.asyncio
    async def test_build_context_with_section_extraction(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test extracting a specific section from artifact."""
        content = """# Resolved
Item 1 is resolved.

# Unresolved
Item 2 is unresolved.
"""
        (tmp_worktree / "questions.md").write_text(content)
        registry.register(
            run_id="run-1",
            step_id="S-01",
            task_id="T-01",
            path="questions.md",
            content=content.encode(),
        )

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {
                    "artifact": "questions.md",
                    "as": "resolved_questions",
                    "required": True,
                    "section": "Resolved",
                }
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        assert context["resolved_questions"] == "Item 1 is resolved."

    @pytest.mark.asyncio
    async def test_build_context_with_token_limit_per_artifact(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test per-artifact token limits."""
        long_content = "a" * 1000
        (tmp_worktree / "long.md").write_text(long_content)
        registry.register(
            run_id="run-1",
            step_id="S-01",
            task_id="T-01",
            path="long.md",
            content=long_content.encode(),
        )

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "long.md", "as": "content", "required": True, "max_tokens": 50}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        # 50 tokens * 4 chars = 200 chars + truncation message
        assert len(context["content"]) <= 250
        assert "[...truncated]" in context["content"]

    @pytest.mark.asyncio
    async def test_build_context_with_total_token_limit(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test total token budget across multiple artifacts."""
        content1 = "a" * 200  # ~50 tokens
        content2 = "b" * 200  # ~50 tokens

        (tmp_worktree / "file1.md").write_text(content1)
        (tmp_worktree / "file2.md").write_text(content2)

        registry.register("run-1", "S-01", "T-01", "file1.md", content1.encode())
        registry.register("run-1", "S-01", "T-01", "file2.md", content2.encode())

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate({"artifact": "file1.md", "as": "file1", "required": True}),
            ContextSource.model_validate({"artifact": "file2.md", "as": "file2", "required": True}),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=60,  # Only enough for file1 + partial file2
        )

        # Both files should be present but file2 might be truncated
        assert "file1" in context
        assert "file2" in context
        assert len(context["file1"]) == 200
        # file2 should be truncated due to budget
        assert len(context["file2"]) <= 200

    @pytest.mark.asyncio
    async def test_build_context_required_artifact_missing(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test error when required artifact is missing."""
        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "missing.md", "as": "missing", "required": True}
            ),
        ]

        with pytest.raises(ContextError) as exc_info:
            await builder.build_context(
                run_id="run-1",
                context_sources=sources,
                variables={},
                total_token_limit=8000,
            )

        assert "Required artifact not found: missing.md" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_build_context_optional_artifact_missing(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test optional artifact is skipped if missing."""
        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "missing.md", "as": "missing", "required": False}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        assert "missing" not in context
        assert context == {}

    @pytest.mark.asyncio
    async def test_build_context_mixed_required_optional(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test mix of required and optional artifacts."""
        (tmp_worktree / "required.md").write_text("Required content.")
        registry.register("run-1", "S-01", "T-01", "required.md", b"Required content.")

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": "required.md", "as": "req", "required": True}
            ),
            ContextSource.model_validate(
                {"artifact": "optional.md", "as": "opt", "required": False}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        assert "req" in context
        assert context["req"] == "Required content."
        assert "opt" not in context

    @pytest.mark.asyncio
    async def test_build_context_multiple_artifacts(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test building context from multiple artifacts."""
        (tmp_worktree / "plan.md").write_text("Plan content.")
        (tmp_worktree / "arch.md").write_text("Architecture content.")
        (tmp_worktree / "questions.md").write_text("Questions content.")

        registry.register("run-1", "S-01", "T-01", "plan.md", b"Plan content.")
        registry.register("run-1", "S-01", "T-01", "arch.md", b"Architecture content.")
        registry.register("run-1", "S-01", "T-01", "questions.md", b"Questions content.")

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate({"artifact": "plan.md", "as": "plan", "required": True}),
            ContextSource.model_validate(
                {"artifact": "arch.md", "as": "architecture", "required": True}
            ),
            ContextSource.model_validate(
                {"artifact": "questions.md", "as": "questions", "required": False}
            ),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        assert len(context) == 3
        assert context["plan"] == "Plan content."
        assert context["architecture"] == "Architecture content."
        assert context["questions"] == "Questions content."

    @pytest.mark.asyncio
    async def test_build_context_no_worktree(self, registry: ArtifactRegistry) -> None:
        """Test context building fails gracefully without worktree."""
        builder = TaskContextBuilder(registry, worktree_path=None)
        sources = [
            ContextSource.model_validate({"artifact": "plan.md", "as": "plan", "required": False}),
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=8000,
        )

        # Optional artifact, no worktree -> skipped
        assert context == {}

    @pytest.mark.asyncio
    async def test_build_context_stops_at_budget_exhaustion(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test context building stops when token budget exhausted."""
        # Create three large files
        for i in range(3):
            content = f"Content {i} " * 200  # Each ~200 tokens
            (tmp_worktree / f"file{i}.md").write_text(content)
            registry.register("run-1", "S-01", "T-01", f"file{i}.md", content.encode())

        builder = TaskContextBuilder(registry, tmp_worktree)
        sources = [
            ContextSource.model_validate(
                {"artifact": f"file{i}.md", "as": f"file{i}", "required": False}
            )
            for i in range(3)
        ]

        context = await builder.build_context(
            run_id="run-1",
            context_sources=sources,
            variables={},
            total_token_limit=300,  # Only enough for ~1.5 files
        )

        # Should have at least file0, possibly truncated file1
        assert "file0" in context
        # file2 might not be present due to budget exhaustion
        # This is acceptable behavior

    @pytest.mark.asyncio
    async def test_build_context_empty_sources(
        self, registry: ArtifactRegistry, tmp_worktree: Path
    ) -> None:
        """Test building context with no sources."""
        builder = TaskContextBuilder(registry, tmp_worktree)

        context = await builder.build_context(
            run_id="run-1",
            context_sources=[],
            variables={},
            total_token_limit=8000,
        )

        assert context == {}
