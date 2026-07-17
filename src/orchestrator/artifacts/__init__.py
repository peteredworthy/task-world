"""Durable content-addressed artifact storage."""

from orchestrator.artifacts.errors import (
    ArtifactError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
)
from orchestrator.artifacts.models import StoredArtifactRef
from orchestrator.artifacts.store import ArtifactStore, FilesystemArtifactStore
from orchestrator.artifacts.coordination import ArtifactRootLock
from orchestrator.artifacts.resolution import (
    ArtifactRootResolutionError,
    ArtifactRootResolver,
    ArtifactStoreResolver,
    ProjectArtifactGarbageCollector,
)
from orchestrator.artifacts.gc import (
    ArtifactGarbageCollectionError,
    ArtifactGarbageCollectionConfigurationError,
    ArtifactGarbageCollectionCoordinator,
    ArtifactGarbageCollector,
    collect_artifact_refs,
    sweep_artifacts,
)

__all__ = [
    "ArtifactError",
    "ArtifactGarbageCollectionError",
    "ArtifactGarbageCollectionConfigurationError",
    "ArtifactGarbageCollectionCoordinator",
    "ArtifactGarbageCollector",
    "ArtifactIntegrityError",
    "ArtifactNotFoundError",
    "ArtifactRootLock",
    "ArtifactRootResolutionError",
    "ArtifactRootResolver",
    "ArtifactStore",
    "collect_artifact_refs",
    "FilesystemArtifactStore",
    "ArtifactStoreResolver",
    "ProjectArtifactGarbageCollector",
    "StoredArtifactRef",
    "sweep_artifacts",
]
