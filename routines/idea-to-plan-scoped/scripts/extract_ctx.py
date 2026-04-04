#!/usr/bin/env python3
"""
extract_ctx.py — Validate step annotations and extract per-step context packets.

Usage:
    python routines/idea-to-plan-scoped/scripts/extract_ctx.py docs/<feature>

What it does:
  1. Validates that every heading in architecture.md (and plan.md if present and tagged)
     is covered by a <!-- steps: ... --> tag — either its own or an ancestor's.
  2. Validates that every [I-XX] item in intent.md has a [→ S-XX] or [→ NO-REQ] annotation.
  3. Discovers all step-*-plan.md files in the feature directory to determine the step set.
  4. For each step (S-01, S-02, ...):
       docs/<feature>/ctx/<stem>-arch.md   — architecture content relevant to that step
       docs/<feature>/ctx/<stem>-plan.md   — plan content relevant to that step (if plan.md tagged)
       docs/<feature>/ctx/<stem>-intent.md — intent lines traced to that step
  5. Exits 0 on success, 1 on any validation failure.

Tagging rules (<!-- steps: ... --> in any heading line):
  - Tags may appear at any heading level (H1–H6).
  - A heading with no tag inherits from its nearest tagged ancestor.
  - A tag on a child overrides the ancestor for that subtree.
  - Special values:
      ALL   — include this section for every step
      NONE  — exclude this section from every step (child tags can still opt back in)
  - Every heading must be covered by its own tag or an ancestor's tag; uncovered
    headings are a validation error.
  - If an LLM decides all content is globally relevant, tagging the document's H1
    with <!-- steps: ALL --> covers everything with one annotation.

Breadcrumb rule:
  If a sub-section IS included for a step but its parent was NOT, the parent heading
  is emitted without its body, giving the included section structural context.
"""

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STEP_ALL = "ALL"
STEP_NONE = "NONE"
STEP_TAG_RE = re.compile(r"<!--\s*steps:\s*([^>]+?)-->")
HEADING_RE = re.compile(r"^(#{1,6})\s+")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One heading + its immediate body lines + child sections."""

    level: int  # 1=H1, 2=H2, …, 6=H6
    raw_heading: str  # original line including tag comment
    explicit_steps: Optional[frozenset]  # None = inherit; frozenset = own tag
    body_lines: list[str] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)

    @property
    def clean_heading(self) -> str:
        """Heading with the <!-- steps: ... --> annotation stripped."""
        return re.sub(r"\s*<!--\s*steps:[^>]+-->", "", self.raw_heading).rstrip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_steps_tag(line: str) -> Optional[frozenset]:
    """
    Extract step tokens from a <!-- steps: ... --> tag.
    Returns None if no tag is present; frozenset (possibly empty) if present.
    Tokens are upper-cased so 'all', 'ALL', 'All' are all treated as ALL.
    """
    m = STEP_TAG_RE.search(line)
    if not m:
        return None
    tokens = frozenset(t.strip().upper() for t in m.group(1).split(",") if t.strip())
    return tokens


def parse_document(text: str) -> tuple[list[str], list[Section]]:
    """
    Parse *text* into a preamble and a tree of Sections.

    Returns:
        preamble_lines  — lines before the first heading (H1–H6)
        roots           — top-level Sections with children populated
    """
    preamble: list[str] = []
    roots: list[Section] = []
    stack: list[Section] = []  # open ancestors, innermost last

    for raw_line in text.splitlines():
        m = HEADING_RE.match(raw_line)
        if m:
            level = len(m.group(1))
            node = Section(
                level=level,
                raw_heading=raw_line,
                explicit_steps=_parse_steps_tag(raw_line),
            )
            # Pop until stack top is a strict ancestor (lower level number)
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
        else:
            if stack:
                stack[-1].body_lines.append(raw_line)
            else:
                preamble.append(raw_line)

    return preamble, roots


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _has_content(node: Section) -> bool:
    """True if the node has at least one non-blank body line (not a pure structural heading)."""
    return any(line.strip() for line in node.body_lines)


def _collect_uncovered(nodes: list[Section], parent_covered: bool) -> list[str]:
    """
    Return raw heading lines for any heading that:
      - has non-blank body content, AND
      - has no tag and no tagged ancestor.

    Structural headings (blank/empty bodies) are exempt — they become breadcrumbs
    automatically and carry no content that could be lost.
    """
    errors: list[str] = []
    for node in nodes:
        this_covered = (node.explicit_steps is not None) or parent_covered
        if not this_covered and _has_content(node):
            errors.append(node.raw_heading.rstrip()[:120])
        errors.extend(_collect_uncovered(node.children, this_covered))
    return errors


def validate_document(label: str, roots: list[Section]) -> list[str]:
    """Return validation error strings for a tagged document."""
    errors: list[str] = []
    uncovered = _collect_uncovered(roots, parent_covered=False)
    if uncovered:
        errors.append(
            f"{label}: {len(uncovered)} heading(s) have no <!-- steps: --> tag (own or inherited):"
        )
        for h in uncovered:
            errors.append(f"    {h}")
        errors.append(
            "    → Add <!-- steps: S-XX --> or <!-- steps: ALL --> to cover them.\n"
            "    → Or put <!-- steps: ALL --> on the H1 to cover the whole document."
        )
    return errors


def validate_intent(intent_text: str) -> list[str]:
    """Return validation error strings for intent.md annotations."""
    errors: list[str] = []
    bare = [
        line
        for line in intent_text.splitlines()
        if re.search(r"\[I-\d+\]", line) and not re.search(r"\[I-\d+\s*→", line)
    ]
    if bare:
        errors.append(f"intent.md: {len(bare)} line(s) with [I-XX] but no → annotation:")
        for line in bare[:8]:
            errors.append(f"    {line.strip()[:120]}")
        if len(bare) > 8:
            errors.append(f"    ... and {len(bare) - 8} more")
        errors.append("    → Add [I-XX → S-NN] or [I-XX → NO-REQ: reason] to each.")
    return errors


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _resolve(node: Section, inherited: frozenset) -> frozenset:
    """Effective step set for *node* — own tag wins, otherwise inherit."""
    return node.explicit_steps if node.explicit_steps is not None else inherited


def _matches(effective: frozenset, step_id: str) -> bool:
    """True if *step_id* should be included given *effective* step set."""
    if STEP_NONE in effective:
        return False
    if STEP_ALL in effective:
        return True
    return step_id in effective


def _extract(node: Section, step_id: str, inherited: frozenset) -> list[str]:
    """
    Recursively extract lines from *node* for *step_id*.

    Returns a list of lines to emit (possibly empty).

    Full inclusion:   heading + body + relevant children
    Breadcrumb only:  heading alone (no body) when a descendant is included but this node isn't
    Excluded:         nothing
    """
    effective = _resolve(node, inherited)
    included = _matches(effective, step_id)

    if included:
        out: list[str] = [node.clean_heading]
        out.extend(node.body_lines)
        for child in node.children:
            child_out = _extract(child, step_id, effective)
            if child_out:
                # Ensure a blank line before each child section
                if out and out[-1] != "":
                    out.append("")
                out.extend(child_out)
        return out

    # Not included — check whether any descendant is
    child_parts: list[list[str]] = []
    for child in node.children:
        part = _extract(child, step_id, effective)
        if part:
            child_parts.append(part)

    if child_parts:
        # Breadcrumb: heading only, no body
        out = [node.clean_heading]
        for part in child_parts:
            if out and out[-1] != "":
                out.append("")
            out.extend(part)
        return out

    return []


def write_doc_packet(
    ctx_dir: Path,
    stem: str,
    step_id: str,
    label: str,
    preamble: list[str],
    roots: list[Section],
) -> tuple[int, int]:
    """
    Write ctx/<stem>-<label>.md for *step_id*.

    Returns (full_sections, breadcrumb_sections) counts at the root level.
    """
    lines: list[str] = [f"# {label} — {step_id}", ""]
    if preamble:
        # Trim trailing blank lines from preamble
        while preamble and not preamble[-1].strip():
            preamble = preamble[:-1]
        lines.extend(preamble)
        lines.append("")

    full = 0
    crumbs = 0
    for root in roots:
        part = _extract(root, step_id, inherited=frozenset())
        if not part:
            continue
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(part)
        # Determine if root was fully included or just a breadcrumb
        eff = _resolve(root, frozenset())
        if _matches(eff, step_id):
            full += 1
        else:
            crumbs += 1

    out = ctx_dir / f"{stem}-{label.lower().replace(' ', '-')}.md"
    out.write_text("\n".join(lines))
    return full, crumbs


# ---------------------------------------------------------------------------
# Intent packet (line-based, unchanged logic)
# ---------------------------------------------------------------------------


def parse_intent_by_step(intent_text: str) -> dict[str, list[str]]:
    """Map step_id → list of intent lines that carry a → annotation pointing at it."""
    step_to_lines: dict[str, list[str]] = defaultdict(list)
    annotation_re = re.compile(r"\[I-\d+\s*→\s*([^\]]+)\]")
    for line in intent_text.splitlines():
        if re.search(r"\[I-\d+\s*→\s*NO-REQ", line):
            continue
        for match in annotation_re.finditer(line):
            for ref in match.group(1).split(","):
                m = re.match(r"(S-\d+)", ref.strip())
                if m:
                    sid = m.group(1)
                    if line not in step_to_lines[sid]:
                        step_to_lines[sid].append(line)
    return dict(step_to_lines)


def write_intent_packet(
    ctx_dir: Path,
    stem: str,
    step_id: str,
    intent_by_step: dict[str, list[str]],
) -> int:
    items = intent_by_step.get(step_id, [])
    lines = [f"# Intent Items — {step_id}", ""]
    lines.extend(items) if items else lines.append("*(No intent items traced to this step.)*")
    (ctx_dir / f"{stem}-intent.md").write_text("\n".join(lines))
    return len(items)


# ---------------------------------------------------------------------------
# Discovery + stats helpers
# ---------------------------------------------------------------------------


def discover_steps(feature_dir: Path) -> list[tuple[str, str]]:
    result = []
    for p in sorted(feature_dir.glob("step-*-plan.md")):
        m = re.match(r"step-(\d+)-plan", p.stem)
        if m:
            result.append((f"S-{m.group(1).zfill(2)}", p.stem))
    return result


def _count_headings(nodes: list[Section]) -> int:
    return sum(1 + _count_headings(n.children) for n in nodes)


def _collect_tag_refs(nodes: list[Section], out: set) -> None:
    for node in nodes:
        if node.explicit_steps:
            out.update(node.explicit_steps)
        _collect_tag_refs(node.children, out)


def _has_any_tag(nodes: list[Section]) -> bool:
    for node in nodes:
        if node.explicit_steps is not None:
            return True
        if _has_any_tag(node.children):
            return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} docs/<feature>")
        print(f"Example: python {sys.argv[0]} docs/better-state")
        sys.exit(1)

    feature_dir = Path(sys.argv[1])
    if not feature_dir.is_dir():
        print(f"ERROR: {feature_dir} is not a directory")
        sys.exit(1)

    arch_path = feature_dir / "architecture.md"
    intent_path = feature_dir / "intent.md"
    plan_path = feature_dir / "plan.md"

    for p in (arch_path, intent_path):
        if not p.exists():
            print(f"ERROR: Missing required file: {p}")
            sys.exit(1)

    arch_text = arch_path.read_text()
    intent_text = intent_path.read_text()

    # Parse architecture.md
    arch_preamble, arch_roots = parse_document(arch_text)
    intent_by_step = parse_intent_by_step(intent_text)

    print(f"Parsed architecture.md: {_count_headings(arch_roots)} heading(s)")
    print(
        f"Parsed intent.md: "
        f"{sum(len(v) for v in intent_by_step.values())} annotated lines "
        f"across {len(intent_by_step)} step(s)"
    )

    # Parse plan.md if it exists and carries any step tags
    plan_preamble: list[str] = []
    plan_roots: list[Section] = []
    process_plan = False
    if plan_path.exists():
        plan_text = plan_path.read_text()
        plan_preamble, plan_roots = parse_document(plan_text)
        process_plan = _has_any_tag(plan_roots)
        if process_plan:
            print(f"Parsed plan.md: {_count_headings(plan_roots)} heading(s) — will scope")
        else:
            print("plan.md has no <!-- steps: --> tags — skipping (pass whole file as context)")

    # Validate
    errors: list[str] = []
    errors.extend(validate_document("architecture.md", arch_roots))
    if process_plan:
        errors.extend(validate_document("plan.md", plan_roots))
    errors.extend(validate_intent(intent_text))

    if errors:
        print("\n✗ VALIDATION FAILED")
        for e in errors:
            print(e)
        sys.exit(1)

    print("✓ Annotations valid")

    # Discover steps
    steps = discover_steps(feature_dir)
    if not steps:
        print(f"ERROR: No step-*-plan.md files found in {feature_dir}")
        sys.exit(1)

    print(f"Discovered {len(steps)} step(s): {[sid for sid, _ in steps]}")

    # Warn about step IDs in tags that have no corresponding plan file
    tag_refs: set = set()
    _collect_tag_refs(arch_roots, tag_refs)
    if process_plan:
        _collect_tag_refs(plan_roots, tag_refs)
    tag_refs.update(intent_by_step.keys())
    plan_ids = {sid for sid, _ in steps}
    orphaned = {s for s in tag_refs if re.match(r"S-\d+", s) and s not in plan_ids}
    if orphaned:
        print(f"WARNING: Step IDs in tags with no plan file: {sorted(orphaned)}")

    # Write packets
    ctx_dir = feature_dir / "ctx"
    ctx_dir.mkdir(exist_ok=True)
    print(f"\nWriting context packets to {ctx_dir}/")

    total_arch_full = total_arch_crumbs = 0
    total_plan_full = total_plan_crumbs = 0
    total_intent = 0

    for step_id, stem in steps:
        arch_full, arch_crumb = write_doc_packet(
            ctx_dir, stem, step_id, "Architecture Context", arch_preamble, arch_roots
        )
        plan_full = plan_crumb = 0
        if process_plan:
            plan_full, plan_crumb = write_doc_packet(
                ctx_dir, stem, step_id, "Plan Context", plan_preamble, plan_roots
            )
        n_intent = write_intent_packet(ctx_dir, stem, step_id, intent_by_step)

        total_arch_full += arch_full
        total_arch_crumbs += arch_crumb
        total_plan_full += plan_full
        total_plan_crumbs += plan_crumb
        total_intent += n_intent

        plan_note = f", plan {plan_full}+{plan_crumb}✦" if process_plan else ""
        print(
            f"  {step_id} ({stem}): "
            f"arch {arch_full} full + {arch_crumb} breadcrumb(s)"
            f"{plan_note}, "
            f"{n_intent} intent line(s)"
        )

    n = len(steps)
    print(f"\n✓ Done — {n} step(s), {2 + process_plan} packet type(s) each")
    print(
        f"  arch:   avg {total_arch_full / n:.1f} full sections, {total_arch_crumbs / n:.1f} breadcrumbs per step"
    )
    if process_plan:
        print(
            f"  plan:   avg {total_plan_full / n:.1f} full sections, {total_plan_crumbs / n:.1f} breadcrumbs per step"
        )
    print(f"  intent: avg {total_intent / n:.1f} lines per step")


if __name__ == "__main__":
    main()
