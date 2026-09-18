import logging

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_app(handler: httpx.MockTransport):
    settings = Settings(
        weknora_base_url="https://kb.example",
        weknora_api_key="wk-super-secret",
        dify_adapter_api_key="adapter-super-secret",
    )
    return create_app(settings=settings, transport=handler)


def test_success_logs_safe_operational_fields_without_sensitive_values(caplog) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": "chunk-1",
                        "content": "retrieved confidential content",
                        "score": 0.9,
                    }
                ],
            },
        )

    app = make_app(httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="weknora_dify_adapter"), TestClient(app) as client:
        response = client.post(
            "/retrieval",
            headers={
                "Authorization": "Bearer adapter-super-secret",
                "X-Request-ID": "request-123",
            },
            json={
                "knowledge_id": "kb-1",
                "query": "full confidential query",
                "retrieval_setting": {"top_k": 5, "score_threshold": 0.5},
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert any(getattr(record, "request_id", None) == "request-123" for record in caplog.records)
    assert any(getattr(record, "knowledge_base_id", None) == "kb-1" for record in caplog.records)
    assert any(getattr(record, "status_code", None) == 200 for record in caplog.records)
    assert any(hasattr(record, "duration_ms") for record in caplog.records)
    assert "adapter-super-secret" not in caplog.text
    assert "wk-super-secret" not in caplog.text
    assert "full confidential query" not in caplog.text
    assert "retrieved confidential content" not in caplog.text


def test_failure_logs_do_not_include_upstream_body_and_unsafe_request_id_is_replaced(
    caplog,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream database password=secret")

    app = make_app(httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="weknora_dify_adapter"), TestClient(app) as client:
        response = client.post(
            "/retrieval",
            headers={
                "Authorization": "Bearer adapter-super-secret",
                "X-Request-ID": "unsafe request id with spaces",
            },
            json={
                "knowledge_id": "kb-1",
                "query": "private question",
                "retrieval_setting": {"top_k": 5, "score_threshold": 0.5},
            },
        )

    assert response.status_code == 502
    assert response.headers["X-Request-ID"] != "unsafe request id with spaces"
    assert "upstream database password=secret" not in caplog.text
    assert "private question" not in caplog.text
