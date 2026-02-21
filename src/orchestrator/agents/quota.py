"""Quota fetching protocol and implementations."""

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

_OPENAI_CREDIT_GRANTS_URL = "https://api.openai.com/dashboard/billing/credit_grants"


@runtime_checkable
class QuotaFetcher(Protocol):
    """Structural protocol for fetching quota information from an LLM provider."""

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]: ...


class HttpQuotaFetcher:
    """Fetches quota data from the OpenAI API via HTTPS."""

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
        """Fetch credit grant information from OpenAI.

        The api_key is never logged at any log level.
        """
        logger.debug("Fetching OpenAI credit grants")
        response = httpx.get(
            _OPENAI_CREDIT_GRANTS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


class FakeQuotaFetcher:
    """Test double that returns a pre-configured response without network calls."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
        return self._response
