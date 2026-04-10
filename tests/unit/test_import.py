"""Test that the package can be imported."""


def test_import_orchestrator() -> None:
    import orchestrator

    assert orchestrator.__version__ == "0.1.0"
