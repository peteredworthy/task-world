"""Auto-discovered agent packages.

Each sub-package registers its agent factory on import via
``agent_factory.register()``.  The ``discover()`` function
imports all sub-packages using ``pkgutil``, triggering registration.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def discover() -> None:
    """Import all agent sub-packages to trigger their register() calls.

    Packages that fail to import (e.g. missing optional dependencies)
    are silently skipped -- the agent simply won't be registered.
    """
    package = importlib.import_module(__name__)
    for info in pkgutil.iter_modules(package.__path__):
        if info.ispkg:
            try:
                importlib.import_module(f"{__name__}.{info.name}")
                logger.debug("Discovered agent package: %s", info.name)
            except Exception:
                logger.debug(
                    "Skipped agent package %s (import failed)",
                    info.name,
                    exc_info=True,
                )
