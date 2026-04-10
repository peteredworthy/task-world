"""Unit tests for repos and agent-runner API schema validators.

Note: URL scheme validation (http/https/ssh/git@) and SSRF protection
(base_url must start with http:// or https://) live in router code, not
Pydantic models, so those checks remain in the integration test suite.
This file covers the pure-Pydantic AddRepoRequest model_validator.
"""

import pytest
from pydantic import ValidationError

from orchestrator.api.schemas.repos import AddRepoRequest


# ---------------------------------------------------------------------------
# AddRepoRequest mutual-exclusion validator
# ---------------------------------------------------------------------------


def test_add_repo_neither_url_nor_path_rejected() -> None:
    """Providing neither url nor path raises ValidationError."""
    with pytest.raises(ValidationError, match="Either url or path"):
        AddRepoRequest()


def test_add_repo_both_url_and_path_rejected() -> None:
    """Providing both url and path raises ValidationError."""
    with pytest.raises(ValidationError, match="either url or path, not both"):
        AddRepoRequest(url="https://example.com/repo.git", path="/tmp/repo")


def test_add_repo_url_only_accepted() -> None:
    """Providing only url is valid."""
    req = AddRepoRequest(url="https://example.com/repo.git")
    assert req.url == "https://example.com/repo.git"
    assert req.path is None


def test_add_repo_path_only_accepted() -> None:
    """Providing only path is valid."""
    req = AddRepoRequest(path="/tmp/repo")
    assert req.path == "/tmp/repo"
    assert req.url is None
