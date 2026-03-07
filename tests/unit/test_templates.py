"""Tests for orchestrator.workflow.templates."""

from __future__ import annotations

from pathlib import Path


from orchestrator.workflow.templates import derive_output_path, resolve_template


class TestResolveTemplate:
    """Tests for resolve_template()."""

    def test_simple_variable(self) -> None:
        result = resolve_template("Branch: {{feature}}", {"feature": "my-feat"})
        assert result == "Branch: my-feat"

    def test_item_stem(self) -> None:
        result = resolve_template("Processing {{item_stem}}", {"item_stem": "step-01"})
        assert result == "Processing step-01"

    def test_output_path(self) -> None:
        result = resolve_template("Write to {{output_path}}", {"output_path": "docs/out.md"})
        assert result == "Write to docs/out.md"

    def test_item_content(self) -> None:
        result = resolve_template(
            "Content: {{item_content}}", {"item_content": "file contents here"}
        )
        assert result == "Content: file contents here"

    def test_file_placeholder(self, tmp_path: Path) -> None:
        readme = tmp_path / "some" / "path.md"
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text("Hello from file")

        result = resolve_template("Read: {{file:some/path.md}}", worktree_path=str(tmp_path))
        assert result == "Read: Hello from file"

    def test_file_not_found(self) -> None:
        result = resolve_template(
            "Read: {{file:nonexistent.md}}", worktree_path="/tmp/does-not-exist"
        )
        assert result == "Read: [File not found: nonexistent.md]"

    def test_file_no_worktree(self, tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("direct read")

        result = resolve_template(f"Read: {{{{file:{target}}}}}")
        assert result == "Read: direct read"

    def test_multiple_variables(self) -> None:
        template = "{{greeting}}, {{name}}! Welcome to {{place}}."
        variables = {"greeting": "Hello", "name": "Alice", "place": "Wonderland"}
        result = resolve_template(template, variables)
        assert result == "Hello, Alice! Welcome to Wonderland."

    def test_no_variables_unchanged(self) -> None:
        template = "No placeholders here."
        assert resolve_template(template) == template

    def test_unknown_variable_left_as_is(self) -> None:
        result = resolve_template("Hello {{unknown}}", {"other": "val"})
        assert result == "Hello {{unknown}}"

    def test_empty_variables_dict(self) -> None:
        result = resolve_template("Hello {{name}}", {})
        assert result == "Hello {{name}}"

    def test_no_recursive_resolution(self) -> None:
        """Variable values containing {{...}} are NOT recursively expanded."""
        result = resolve_template("Result: {{outer}}", {"outer": "has {{inner}}", "inner": "deep"})
        assert result == "Result: has {{inner}}"

    def test_whitespace_in_placeholder(self) -> None:
        """Whitespace around key is stripped."""
        result = resolve_template("{{ feature }}", {"feature": "trimmed"})
        assert result == "trimmed"

    def test_repeated_placeholder(self) -> None:
        result = resolve_template("{{x}} and {{x}}", {"x": "same"})
        assert result == "same and same"


class TestDeriveOutputPath:
    """Tests for derive_output_path()."""

    def test_basic_stem_replacement(self) -> None:
        result = derive_output_path(
            "docs/dry-run/{{item_stem}}-notes.md",
            "docs/steps/step-01.md",
        )
        assert result == "docs/dry-run/step-01-notes.md"

    def test_with_additional_variables(self) -> None:
        result = derive_output_path(
            "docs/{{feature}}/{{item_stem}}.md",
            "inputs/overview.txt",
            variables={"feature": "auth"},
        )
        assert result == "docs/auth/overview.md"

    def test_no_stem_placeholder(self) -> None:
        result = derive_output_path("output/fixed-name.md", "anything.py")
        assert result == "output/fixed-name.md"

    def test_nested_input_path(self) -> None:
        result = derive_output_path(
            "out/{{item_stem}}.json",
            "a/b/c/deeply-nested.yaml",
        )
        assert result == "out/deeply-nested.json"
