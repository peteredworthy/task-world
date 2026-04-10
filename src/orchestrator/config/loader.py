"""Load routine definitions from YAML files.

This module re-exports the loader from orchestrator.config.routines.loader for
compatibility with the src/orchestrator/config/loader.py path.
"""

from orchestrator.config.routines.loader import load_routine_from_path

__all__ = ["load_routine_from_path"]
