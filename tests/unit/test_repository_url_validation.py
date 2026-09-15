"""Pure URL-prefix contracts used by repository and model-discovery APIs."""

import pytest

from orchestrator.api import is_supported_model_base_url, is_supported_repository_url


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com/repo.git",
        "https://example.com/repo.git",
        "ssh://example.com/repo.git",
        "git@example.com:org/repo.git",
    ],
)
def test_repository_url_accepts_all_supported_clone_forms(value: str) -> None:
    assert is_supported_repository_url(value)


@pytest.mark.parametrize("value", ["file:///tmp/repo", "ftp://example.com/repo.git", "", "/tmp/repo"])
def test_repository_url_rejects_unsupported_clone_forms(value: str) -> None:
    assert not is_supported_repository_url(value)


@pytest.mark.parametrize("value", ["http://127.0.0.1:1234", "https://models.example.test/"])
def test_model_discovery_accepts_http_urls(value: str) -> None:
    assert is_supported_model_base_url(value)


@pytest.mark.parametrize("value", ["file:///etc/passwd", "ftp://models.example.test", "ssh://host"])
def test_model_discovery_rejects_non_http_urls(value: str) -> None:
    assert not is_supported_model_base_url(value)
