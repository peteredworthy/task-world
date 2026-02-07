"""End-to-end tests for the orchestrator system.

E2E tests run against a real HTTP server in a subprocess and use real
HTTP requests (not TestClient). They test the complete system behavior
including server startup, state persistence, and concurrent operations.

Run with: pytest tests/e2e -v --tb=short
"""
