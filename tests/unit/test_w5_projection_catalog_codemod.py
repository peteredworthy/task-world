from scripts.codemods.w5_projection_catalog import transform


def test_projection_catalog_codemod_injects_required_dependencies() -> None:
    source = """from orchestrator.graph import reduce_event\n\nresult = reduce_event(state, event)\nstore = GraphEventStore(session)\n"""

    transformed, changed = transform(source)

    assert changed
    assert "reduce_event(build_graph_catalog(), state, event)" in transformed
    assert "GraphEventStore(session, build_graph_catalog())" in transformed
    assert "from orchestrator.graph import build_graph_catalog" in transformed


def test_projection_catalog_codemod_is_idempotent() -> None:
    source = """from orchestrator.graph import build_graph_catalog\n\nprojection = project_run_state(build_graph_catalog(), events)\n"""

    transformed, changed = transform(source)

    assert transformed == source
    assert not changed
