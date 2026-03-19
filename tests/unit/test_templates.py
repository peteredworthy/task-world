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

    # --- Two-pass resolution tests ---

    def test_file_with_variable_in_path(self, tmp_path: Path) -> None:
        """{{file:docs/{{feature}}/plan.md}} resolves variable first, then reads file."""
        doc = tmp_path / "docs" / "auth" / "plan.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("Auth plan content")

        result = resolve_template(
            "Context: {{file:docs/{{feature}}/plan.md}}",
            {"feature": "auth"},
            worktree_path=str(tmp_path),
        )
        assert result == "Context: Auth plan content"

    def test_file_with_multiple_variables_in_path(self, tmp_path: Path) -> None:
        """Multiple variables inside a file: path are resolved."""
        doc = tmp_path / "docs" / "v2" / "auth" / "spec.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("v2 auth spec")

        result = resolve_template(
            "{{file:docs/{{version}}/{{feature}}/spec.md}}",
            {"version": "v2", "feature": "auth"},
            worktree_path=str(tmp_path),
        )
        assert result == "v2 auth spec"

    def test_file_variable_not_found_leaves_placeholder(self) -> None:
        """If the variable inside file: path is unknown, path stays unresolved."""
        result = resolve_template(
            "{{file:docs/{{feature}}/plan.md}}",
            {},
            worktree_path="/tmp/nonexistent",
        )
        # Variable not resolved → file path contains literal {{feature}}
        assert "File not found" in result or "{{feature}}" in result

    def test_plain_variable_and_file_mixed(self, tmp_path: Path) -> None:
        """Plain variables and file references coexist correctly."""
        doc = tmp_path / "readme.md"
        doc.write_text("README")

        result = resolve_template(
            "Branch: {{branch}} | Docs: {{file:readme.md}}",
            {"branch": "main"},
            worktree_path=str(tmp_path),
        )
        assert result == "Branch: main | Docs: README"

    def test_pass1_does_not_resolve_file_refs(self, tmp_path: Path) -> None:
        """file: refs survive pass 1 even when there are no variables to resolve."""
        doc = tmp_path / "data.txt"
        doc.write_text("data content")

        result = resolve_template(
            "{{file:data.txt}}",
            worktree_path=str(tmp_path),
        )
        assert result == "data content"


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
