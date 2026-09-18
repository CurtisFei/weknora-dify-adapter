from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VALID_BODY = {
    "knowledge_id": "kb-1",
    "query": "refund policy",
    "retrieval_setting": {"top_k": 5, "score_threshold": 0.5},
}
AUTH_HEADERS = {"Authorization": "Bearer adapter-secret"}


def make_settings() -> Settings:
    return Settings(
        weknora_base_url="https://kb.example",
        weknora_api_key="wk-secret",
        dify_adapter_api_key="adapter-secret",
        weknora_timeout_seconds=1,
    )


@contextmanager
def api_client(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> Iterator[TestClient]:
    if handler is None:

        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": True, "data": []})

    app = create_app(settings=make_settings(), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        yield client


def test_healthz_does_not_require_authentication() -> None:
    with api_client() as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer wrong"}],
)
def test_retrieval_rejects_missing_or_invalid_credentials(headers: dict[str, str]) -> None:
    with api_client() as client:
        response = client.post("/retrieval", headers=headers, json=VALID_BODY)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error_code"] == "unauthorized"


def test_retrieval_calls_weknora_and_maps_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": "chunk-1",
                        "content": "answer context",
                        "score": 0.9,
                        "knowledge_title": "Guide",
                    }
                ],
            },
        )

    with api_client(handler) as client:
        response = client.post("/retrieval", headers=AUTH_HEADERS, json=VALID_BODY)

    assert response.status_code == 200
    assert response.json()["records"][0]["content"] == "answer context"
    upstream = captured["request"]
    assert isinstance(upstream, httpx.Request)
    assert upstream.headers["X-API-Key"] == "wk-secret"


def test_retrieval_short_circuits_mismatched_kb_filter() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    body = {
        **VALID_BODY,
        "metadata_condition": {
            "logical_operator": "and",
            "conditions": [
                {
                    "name": "knowledge_base_id",
                    "comparison_operator": "is",
                    "value": "kb-other",
                }
            ],
        },
    }
    with api_client(handler) as client:
        response = client.post("/retrieval", headers=AUTH_HEADERS, json=body)

    assert response.status_code == 200
    assert response.json() == {"records": []}
    assert calls == 0


def test_retrieval_returns_stable_validation_error() -> None:
    with api_client() as client:
        response = client.post(
            "/retrieval",
            headers=AUTH_HEADERS,
            json={**VALID_BODY, "query": "   "},
        )

    assert response.status_code == 400
    assert response.json() == {
        "error_code": "invalid_request",
        "message": "Request validation failed",
    }


def test_retrieval_returns_metadata_mapping_error() -> None:
    body = {
        **VALID_BODY,
        "metadata_condition": {
            "logical_operator": "or",
            "conditions": [],
        },
    }
    with api_client() as client:
        response = client.post("/retrieval", headers=AUTH_HEADERS, json=body)

    assert response.status_code == 400
    assert response.json()["error_code"] == "unsupported_metadata_condition"


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (401, 401, "upstream_unauthorized"),
        (403, 403, "upstream_forbidden"),
        (500, 502, "upstream_error"),
    ],
)
def test_retrieval_maps_upstream_statuses(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, text="private details")

    with api_client(handler) as client:
        response = client.post("/retrieval", headers=AUTH_HEADERS, json=VALID_BODY)

    assert response.status_code == expected_status
    assert response.json()["error_code"] == expected_code
    assert "private details" not in response.text
