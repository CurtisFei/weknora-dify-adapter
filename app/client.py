"""Asynchronous WeKnora HTTP client."""

from typing import Any
from urllib.parse import quote

import httpx

from app.errors import AdapterError


class WeKnoraClient:
    """Minimal client for WeKnora's per-KB hybrid-search endpoint."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._http_client = http_client

    async def hybrid_search(
        self,
        knowledge_base_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a WeKnora search and return its decoded JSON envelope."""

        path_id = quote(knowledge_base_id, safe="")
        url = f"{self._api_url}/knowledge-bases/{path_id}/hybrid-search"
        try:
            response = await self._http_client.post(
                url,
                headers={"X-API-Key": self._api_key},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise AdapterError(
                504,
                "upstream_timeout",
                "WeKnora did not respond before the configured timeout",
            ) from exc
        except httpx.RequestError as exc:
            raise AdapterError(
                502,
                "upstream_unavailable",
                "WeKnora could not be reached",
            ) from exc

        if response.status_code == 401:
            raise AdapterError(401, "upstream_unauthorized", "WeKnora rejected the API key")
        if response.status_code == 403:
            raise AdapterError(403, "upstream_forbidden", "WeKnora denied knowledge-base access")
        if not response.is_success:
            raise AdapterError(
                502,
                "upstream_error",
                f"WeKnora returned HTTP {response.status_code}",
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise AdapterError(
                502,
                "invalid_upstream_response",
                "WeKnora returned invalid JSON",
            ) from exc
        if not isinstance(result, dict):
            raise AdapterError(
                502,
                "invalid_upstream_response",
                "WeKnora returned an invalid JSON document",
            )
        return {str(key): value for key, value in result.items()}
