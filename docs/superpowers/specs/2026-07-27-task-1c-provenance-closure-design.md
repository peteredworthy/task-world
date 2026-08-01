# Task 1c Provenance Closure Design

## Goal

Close the final false-trust and escape-detection gaps in the bounded
`GraphProjection` inventory without adding general type inference.

## Design

The inventory builds one immutable per-module symbol table from explicit,
fully-qualified approved origins. `orchestrator.graph.GraphProjection`, the
approved graph producers/types/fields, and `typing.cast` are recognized only
when their actual import origin is approved. A same-tail foreign import is not
equivalent. Local definitions, parameters, and assignments shadow and
invalidate imported symbols in their lexical scope.

The same table records a callable signature for every local callable: its
ordered positional-only, positional-or-keyword, keyword-only, and variadic
parameters, plus the exact parameters annotated as `GraphProjection`. The
collector binds a call using Python argument rules. A tracked argument is safe
only when it binds unambiguously to one of those projection parameters;
otherwise the collector emits a bounded diagnostic rather than inferring a
type.

Projection-bearing collection literals recurse through lists, tuples, sets,
and dict values. At every value boundary—return, plain or annotated
assignment, call/constructor argument, and nested collection—the outermost
unsupported escape produces one diagnostic and child diagnostics are
suppressed.

## Verification

Adversarial unit tests cover foreign same-tail imports, shadows of imported
`cast`, producer and constructor shadows, reordered and keyword call binding,
malformed and variadic calls, and all nested collection boundaries. A test
generates the repository diagnostic report and compares it byte-for-byte with
the checked-in diagnostics artifact. The artifact is regenerated only from
`--diagnose` output. Targeted tests, Ruff, Pyright, the diagnostic command,
and the full suite are required before commit.
