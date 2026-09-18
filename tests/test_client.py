import json
from collections.abc import Callable

import httpx
import pytest

from app.client import WeKnoraClient
from app.errors import AdapterError


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[WeKnoraClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        WeKnoraClient(
            api_url="https://kb.example/api/v1",
            api_key="wk-secret",
            http_client=http_client,
        ),
        http_client,
    )


@pytest.mark.asyncio
async def test_hybrid_search_sends_expected_request_and_escapes_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"success": True, "data": []})

    client, http_client = make_client(handler)
    try:
        result = await client.hybrid_search("kb/with space", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert request.url.raw_path == b"/api/v1/knowledge-bases/kb%2Fwith%20space/hybrid-search"
    assert request.headers["X-API-Key"] == "wk-secret"
    assert json.loads(request.content) == {"query_text": "refund"}
    assert result == {"success": True, "data": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream_status", [401, 403])
async def test_hybrid_search_preserves_upstream_auth_status(upstream_status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, text="sensitive upstream body")

    client, http_client = make_client(handler)
    try:
        with pytest.raises(AdapterError) as exc_info:
            await client.hybrid_search("kb-1", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    assert exc_info.value.status_code == upstream_status
    assert "sensitive upstream body" not in exc_info.value.message


@pytest.mark.asyncio
async def test_hybrid_search_maps_other_upstream_errors_to_502() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="database host and password")

    client, http_client = make_client(handler)
    try:
        with pytest.raises(AdapterError) as exc_info:
            await client.hybrid_search("kb-1", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "upstream_error"
    assert "database host and password" not in exc_info.value.message


@pytest.mark.asyncio
async def test_hybrid_search_rejects_invalid_json() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client, http_client = make_client(handler)
    try:
        with pytest.raises(AdapterError) as exc_info:
            await client.hybrid_search("kb-1", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "invalid_upstream_response"


@pytest.mark.asyncio
async def test_hybrid_search_maps_timeout_to_504() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with wk-secret", request=request)

    client, http_client = make_client(handler)
    try:
        with pytest.raises(AdapterError) as exc_info:
            await client.hybrid_search("kb-1", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    assert exc_info.value.status_code == 504
    assert exc_info.value.error_code == "upstream_timeout"
    assert "wk-secret" not in exc_info.value.message


@pytest.mark.asyncio
async def test_hybrid_search_maps_connection_failure_to_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("host includes wk-secret", request=request)

    client, http_client = make_client(handler)
    try:
        with pytest.raises(AdapterError) as exc_info:
            await client.hybrid_search("kb-1", {"query_text": "refund"})
    finally:
        await http_client.aclose()

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "upstream_unavailable"
    assert "wk-secret" not in exc_info.value.message
