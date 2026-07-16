"""Errors raised by durable artifact storage."""


class ArtifactError(Exception):
    """Base class for artifact storage errors."""


class ArtifactNotFoundError(ArtifactError):
    """The referenced artifact does not exist."""


class ArtifactIntegrityError(ArtifactError):
    """The referenced artifact is malformed or has changed."""
