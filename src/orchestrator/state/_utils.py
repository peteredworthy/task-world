"""Internal utilities for state module. Not part of the public API."""

from uuid import uuid4


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid4())
