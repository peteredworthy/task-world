#!/usr/bin/env python3
"""
extract_ctx.py — Validate architecture.md annotations and extract per-step context packets.

Usage:
    python routines/idea-to-plan-scoped/scripts/extract_ctx.py docs/<feature>

What it does:
  1. Validates that every ## section in architecture.md has a <!-- steps: S-XX, ... --> tag.
  2. Validates that every [I-XX] item in intent.md has a [→ S-XX] or [→ NO-REQ] annotation.
  3. Discovers all step-*-plan.md files in the feature directory to determine the step set.
  4. For each step (S-01, S-02, ...):
       docs/<feature>/ctx/<stem>-arch.md   — architecture sections relevant to that step
       docs/<feature>/ctx/<stem>-intent.md — intent lines traced to that step
     where <stem> is the step plan filename stem (e.g. step-01-plan).
  5. Exits 0 on success, 1 on any validation failure.

Run this at the end of S-03/T-01 to confirm annotations are correct AND produce the
per-step packets that S-04 and S-05 fan-out agents will consume.
The ctx/ directory is a temporary artifact — it is removed by the S-08 cleanup task.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_architecture(arch_text: str):
    """
    Split architecture.md into sections.

    Only ## (H2) headings are treated as section boundaries.
    ### sub-headings are included in their parent section's body.

    Returns:
        preamble_lines: list[str]   — lines before the first ## heading
        sections: list[tuple]       — (raw_heading_line, body_text, steps_set)
    """
    preamble: list[str] = []
    sections: list[tuple] = []

    current_heading: str | None = None
    current_body: list[str] = []
    current_steps: set[str] = set()
    found_first_h2 = False

    for line in arch_text.splitlines():
        h2 = re.match(r"^##\s+", line) and not re.match(r"^###", line)
        if h2:
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_body), current_steps))
            elif found_first_h2 is False and current_body:
                preamble = current_body[:]
            found_first_h2 = True
            current_heading = line
            current_body = []
            # Extract <!-- steps: ... --> from heading
            m = re.search(r"<!--\s*steps:\s*([^>]+?)-->", line)
            current_steps = set()
            if m:
                current_steps = {s.strip() for s in m.group(1).split(",") if s.strip()}
        else:
            if not found_first_h2:
                preamble.append(line)
            else:
                current_body.append(line)

    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_body), current_steps))

    return preamble, sections


def parse_intent_by_step(intent_text: str) -> dict[str, list[str]]:
    """
    Return a mapping of step_id -> list of lines from intent.md that carry
    a [I-XX → S-XX/...] annotation pointing at that step.

    Lines with [I-XX → NO-REQ] are skipped.
    Lines with multiple step references contribute to each referenced step.
    """
    step_to_lines: dict[str, list[str]] = defaultdict(list)
    annotation_re = re.compile(r"\[I-\d+\s*→\s*([^\]]+)\]")

    for line in intent_text.splitlines():
        if re.search(r"\[I-\d+\s*→\s*NO-REQ", line):
            continue
        for match in annotation_re.finditer(line):
            refs = match.group(1).split(",")
            for ref in refs:
                # Ref may be "S-02/T-01/R1" or just "S-02"
                step_match = re.match(r"(S-\d+)", ref.strip())
                if step_match:
                    sid = step_match.group(1)
                    if line not in step_to_lines[sid]:
                        step_to_lines[sid].append(line)
    return dict(step_to_lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(feature_dir: Path, sections, intent_text: str) -> list[str]:
    """Return a list of error messages; empty list means all valid."""
    errors: list[str] = []

    # 1. Every ## section must be annotated
    unannotated = [h for h, _, steps in sections if not steps]
    if unannotated:
        errors.append(
            f"architecture.md: {len(unannotated)} ## section(s) lack a <!-- steps: S-XX --> tag:"
        )
        for h in unannotated:
            errors.append(f"    {h.rstrip()[:100]}")
        errors.append("    → Add <!-- steps: S-XX, S-YY --> to each section heading.")

    # 2. Every [I-XX] in intent.md must have a → annotation
    bare_lines = [
        line
        for line in intent_text.splitlines()
        if re.search(r"\[I-\d+\]", line) and not re.search(r"\[I-\d+\s*→", line)
    ]
    if bare_lines:
        errors.append(f"intent.md: {len(bare_lines)} line(s) with [I-XX] but no → annotation:")
        for line in bare_lines[:8]:
            errors.append(f"    {line.strip()[:120]}")
        if len(bare_lines) > 8:
            errors.append(f"    ... and {len(bare_lines) - 8} more")
        errors.append("    → Add [I-XX → S-NN] or [I-XX → NO-REQ: reason] to each.")

    return errors


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_steps(feature_dir: Path) -> list[tuple[str, str]]:
    """
    Return list of (step_id, file_stem) pairs sorted by step number.
    e.g. [("S-01", "step-01-plan"), ("S-02", "step-02-plan"), ...]
    """
    plan_files = sorted(feature_dir.glob("step-*-plan.md"))
    result = []
    for p in plan_files:
        # Extract the two-digit number from "step-NN-plan.md"
        m = re.match(r"step-(\d+)-plan", p.stem)
        if m:
            num = m.group(1).zfill(2)
            result.append((f"S-{num}", p.stem))
    return result


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def write_arch_packet(
    ctx_dir: Path,
    stem: str,
    step_id: str,
    preamble: list[str],
    sections: list[tuple],
) -> int:
    """Write ctx/<stem>-arch.md; returns number of sections included."""
    # Validation guarantees all sections are annotated, so unannotated sections
    # won't appear in practice. Include only sections tagged for this step.
    relevant = [(h, body) for h, body, steps in sections if step_id in steps]

    lines = [f"# Architecture Context — {step_id}", ""]
    if preamble:
        lines.extend(preamble)
        lines.append("")
    for heading, body in relevant:
        # Strip annotation comment from heading for cleaner agent reading
        clean = re.sub(r"\s*<!--\s*steps:[^>]+-->", "", heading)
        lines.append(clean)
        lines.append(body)
        lines.append("")

    out = ctx_dir / f"{stem}-arch.md"
    out.write_text("\n".join(lines))
    return len(relevant)


def write_intent_packet(
    ctx_dir: Path,
    stem: str,
    step_id: str,
    intent_by_step: dict[str, list[str]],
) -> int:
    """Write ctx/<stem>-intent.md; returns number of lines included."""
    items = intent_by_step.get(step_id, [])
    lines = [f"# Intent Items — {step_id}", ""]
    if items:
        lines.extend(items)
    else:
        lines.append("*(No intent items directly traced to this step.)*")
    out = ctx_dir / f"{stem}-intent.md"
    out.write_text("\n".join(lines))
    return len(items)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
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

    # Check required files exist
    missing = [p for p in (arch_path, intent_path) if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: Missing required file: {p}")
        sys.exit(1)

    arch_text = arch_path.read_text()
    intent_text = intent_path.read_text()

    # Parse
    preamble, sections = parse_architecture(arch_text)
    intent_by_step = parse_intent_by_step(intent_text)

    print(f"Parsed architecture.md: {len(sections)} ## sections")
    print(
        f"Parsed intent.md: {sum(len(v) for v in intent_by_step.values())} annotated lines "
        f"across {len(intent_by_step)} steps"
    )

    # Validate
    errors = validate(feature_dir, sections, intent_text)
    if errors:
        print("\n✗ VALIDATION FAILED")
        for e in errors:
            print(e)
        sys.exit(1)

    print("✓ Annotations valid")

    # Discover steps from step plan files
    steps = discover_steps(feature_dir)
    if not steps:
        print("ERROR: No step-*-plan.md files found in", feature_dir)
        sys.exit(1)

    print(f"Discovered {len(steps)} steps: {[sid for sid, _ in steps]}")

    # Check for steps referenced in annotations but not in plan files
    annotated_step_ids = {sid for _, _, steps_set in sections for sid in steps_set}
    annotated_step_ids |= set(intent_by_step.keys())
    plan_step_ids = {sid for sid, _ in steps}
    orphaned = annotated_step_ids - plan_step_ids
    if orphaned:
        print(
            f"WARNING: Steps referenced in annotations but no step plan file found: "
            f"{sorted(orphaned)}"
        )

    # Write context packets
    ctx_dir = feature_dir / "ctx"
    ctx_dir.mkdir(exist_ok=True)

    print(f"\nWriting context packets to {ctx_dir}/")
    total_arch_sections = 0
    total_intent_lines = 0

    for step_id, stem in steps:
        n_arch = write_arch_packet(ctx_dir, stem, step_id, preamble, sections)
        n_intent = write_intent_packet(ctx_dir, stem, step_id, intent_by_step)
        total_arch_sections += n_arch
        total_intent_lines += n_intent
        print(f"  {step_id} ({stem}): {n_arch} arch sections, {n_intent} intent lines")

    # Summary
    shared = [(h, s) for h, _, s in sections if len(s) > 1]
    print("\n✓ Done")
    print(f"  {len(steps)} context packet pairs written")
    print(f"  {len(shared)} architecture section(s) shared across multiple steps")
    if shared:
        for h, s in shared:
            clean = re.sub(r"\s*<!--[^>]+-->", "", h).strip()
            print(f"    '{clean[:60]}' → {sorted(s)}")
    print(f"  Avg arch sections per step: {total_arch_sections / len(steps):.1f}")
    print(f"  Avg intent lines per step:  {total_intent_lines / len(steps):.1f}")


if __name__ == "__main__":
    main()
