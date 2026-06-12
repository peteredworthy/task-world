"""Compatibility shim for bare Python commands in this src-layout checkout."""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "orchestrator"

__path__ = [str(_SRC_PACKAGE)]

with (_SRC_PACKAGE / "__init__.py").open(encoding="utf-8") as _init_file:
    exec(compile(_init_file.read(), str(_SRC_PACKAGE / "__init__.py"), "exec"), globals())
