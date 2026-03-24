"""Signal handler decorator and registry for RunWorkflow typed handlers.

Provides @signal_handler(signal_type) decorator that marks a method as
the handler for a specific WorkflowSignal type.  build_registry() scans
an instance and returns the dispatch table used by RunWorkflow.on_signal().
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from orchestrator.workflow.signals import WorkflowSignal

F = TypeVar("F", bound=Callable[..., Any])

# Attribute name used to tag decorated methods
_SIGNAL_TYPE_ATTR = "__signal_type__"


def signal_handler(signal_type: WorkflowSignal) -> Callable[[F], F]:
    """Decorator that registers a method as a handler for a WorkflowSignal type.

    Usage::

        @signal_handler(WorkflowSignal.PAUSE)
        async def handle_pause(self, session, service, payload):
            ...

    The decorated method should be an async method with signature::

        async def handle_*(self, session, service, payload) -> bool

    Return True to stop the execution loop, False to continue.
    """

    def decorator(func: F) -> F:
        setattr(func, _SIGNAL_TYPE_ATTR, signal_type)
        return func

    return decorator


def build_registry(instance: object) -> dict[WorkflowSignal, Callable[..., Any]]:
    """Build a signal handler registry from @signal_handler decorated methods.

    Scans the instance's class for methods decorated with @signal_handler
    and returns a dict mapping WorkflowSignal -> bound method.
    """
    registry: dict[WorkflowSignal, Callable[..., Any]] = {}
    cls = type(instance)
    for name in dir(cls):
        cls_method: object = getattr(cls, name, None)
        if cls_method is not None and hasattr(cls_method, _SIGNAL_TYPE_ATTR):
            sig_type: WorkflowSignal = getattr(cls_method, _SIGNAL_TYPE_ATTR)
            registry[sig_type] = getattr(instance, name)
    return registry
