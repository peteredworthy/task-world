"""Re-export shim for the FastAPI application.

The signal consumer (SignalConsumer) is started in the app lifespan; see
``orchestrator.api.app.create_app`` for the actual implementation.
"""

from orchestrator.workflow import SignalConsumer as SignalConsumer  # noqa: F401
