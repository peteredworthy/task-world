"""Quota fetching protocol and implementations."""

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_OPENAI_SUBSCRIPTION_URL = "https://api.openai.com/v1/dashboard/billing/subscription"
_OPENAI_USAGE_URL = "https://api.openai.com/v1/usage"


@runtime_checkable
class QuotaFetcher(Protocol):
    """Structural protocol for fetching quota information from an LLM provider."""

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]: ...


class HttpQuotaFetcher:
    """Fetches quota data from the OpenAI billing API via HTTPS.

    Uses two endpoints:
    - ``/v1/dashboard/billing/subscription`` — provides the hard spend limit
      (``hard_limit_usd``).
    - ``/v1/usage`` — provides total usage to date (``total_usage_usd``).

    Both endpoints require an account-level (non-project) API key.  Project
    keys (``sk-proj-*``) receive 403 responses; ``get_quota()`` on the
    calling agent swallows those exceptions and returns ``None`` gracefully.

    The api_key is never logged at any log level.
    """

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
        """Fetch subscription limit and usage from OpenAI.

        Returns a dict with ``total_granted`` (hard limit) and ``total_used``
        (cumulative usage), matching the shape expected by agent ``get_quota()``
        implementations and ``FakeQuotaFetcher``.
        """
        logger.debug("Fetching OpenAI billing quota")
        headers = {"Authorization": f"Bearer {api_key}"}

        sub_resp = httpx.get(_OPENAI_SUBSCRIPTION_URL, headers=headers)
        sub_resp.raise_for_status()
        subscription: dict[str, Any] = sub_resp.json()

        usage_resp = httpx.get(_OPENAI_USAGE_URL, headers=headers)
        usage_resp.raise_for_status()
        usage: dict[str, Any] = usage_resp.json()

        return {
            "total_granted": float(subscription["hard_limit_usd"]),
            "total_used": float(usage["total_usage_usd"]),
        }


class FakeQuotaFetcher:
    """Test double that returns a pre-configured response without network calls."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
        return self._response
