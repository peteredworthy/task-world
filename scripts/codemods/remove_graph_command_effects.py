"""Remove the retired graph command-effects injection keyword mechanically."""

from __future__ import annotations

import argparse
from pathlib import Path

import libcst as cst


class _RemoveGraphCommandEffects(cst.CSTTransformer):
    def __init__(self) -> None:
        self.changes = 0

    def leave_Call(self, original: cst.Call, updated: cst.Call) -> cst.Call:
        retained = tuple(
            arg
            for arg in updated.args
            if arg.keyword is None or arg.keyword.value != "future_effects"
        )
        if len(retained) == len(updated.args):
            return updated
        self.changes += len(updated.args) - len(retained)
        if retained:
            retained = (*retained[:-1], retained[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT))
        return updated.with_changes(args=retained)


def transform(source: str) -> tuple[str, int]:
    if "future_effects" not in source:
        return source, 0
    module = cst.parse_module(source)
    transformer = _RemoveGraphCommandEffects()
    transformed = module.visit(transformer)
    return transformed.code, transformer.changes


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--assert-clean", action="store_true")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    dirty: list[Path] = []
    for root in args.paths:
        paths = root.rglob("*.py") if root.is_dir() else (root,)
        for path in paths:
            source = path.read_text()
            output, changes = transform(source)
            if changes == 0:
                continue
            dirty.append(path)
            if args.apply:
                path.write_text(output)
    if not args.apply:
        for path in dirty:
            print(path)
    return 1 if args.assert_clean and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
