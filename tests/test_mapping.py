import pytest
from pydantic import ValidationError

from app.errors import AdapterError
from app.mapping import map_request, map_response
from app.models import DifyRetrievalRequest


def make_request(**overrides: object) -> DifyRetrievalRequest:
    body: dict[str, object] = {
        "knowledge_id": "kb-1",
        "query": "refund policy",
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.5},
    }
    body.update(overrides)
    return DifyRetrievalRequest.model_validate(body)


def test_map_request_without_filters() -> None:
    mapped = map_request(make_request(query="  refund policy  "))

    assert mapped.knowledge_base_id == "kb-1"
    assert mapped.short_circuit_empty is False
    assert mapped.payload == {
        "query_text": "refund policy",
        "match_count": 5,
        "vector_threshold": 0.5,
        "disable_keywords_match": True,
        "disable_vector_match": False,
    }


def test_map_request_adds_document_and_tag_filters() -> None:
    request = make_request(
        metadata_condition={
            "logical_operator": "and",
            "conditions": [
                {
                    "name": "knowledge_id",
                    "comparison_operator": "in",
                    "value": ["doc-1", "doc-2", "doc-1"],
                },
                {
                    "name": "tag_ids",
                    "comparison_operator": "in",
                    "value": ["tag-2", "tag-1", "tag-2"],
                },
            ],
        }
    )

    mapped = map_request(request)

    assert mapped.payload["knowledge_ids"] == ["doc-1", "doc-2"]
    assert mapped.payload["tag_ids"] == ["tag-2", "tag-1"]


def test_mismatched_knowledge_base_filter_short_circuits() -> None:
    request = make_request(
        metadata_condition={
            "logical_operator": "and",
            "conditions": [
                {
                    "name": "knowledge_base_id",
                    "comparison_operator": "is",
                    "value": "kb-other",
                }
            ],
        }
    )

    mapped = map_request(request)

    assert mapped.short_circuit_empty is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query", "   "),
        ("knowledge_id", ""),
        ("retrieval_setting", {"top_k": 0, "score_threshold": 0.5}),
        ("retrieval_setting", {"top_k": 101, "score_threshold": 0.5}),
        ("retrieval_setting", {"top_k": 5, "score_threshold": -0.01}),
        ("retrieval_setting", {"top_k": 5, "score_threshold": 1.01}),
    ],
)
def test_request_validation_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_request(**{field: value})


@pytest.mark.parametrize(
    "metadata_condition",
    [
        {
            "logical_operator": "or",
            "conditions": [{"name": "knowledge_id", "comparison_operator": "is", "value": "doc-1"}],
        },
        {
            "logical_operator": "and",
            "conditions": [{"name": "department", "comparison_operator": "is", "value": "finance"}],
        },
        {
            "logical_operator": "and",
            "conditions": [
                {
                    "name": "knowledge_id",
                    "comparison_operator": "contains",
                    "value": "doc",
                }
            ],
        },
        {
            "logical_operator": "and",
            "conditions": [{"name": "knowledge_id", "comparison_operator": "in", "value": "doc-1"}],
        },
    ],
)
def test_unsupported_metadata_conditions_are_rejected(
    metadata_condition: dict[str, object],
) -> None:
    with pytest.raises(AdapterError) as exc_info:
        map_request(make_request(metadata_condition=metadata_condition))

    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "unsupported_metadata_condition"


def test_conflicting_repeated_document_filters_are_rejected() -> None:
    request = make_request(
        metadata_condition={
            "logical_operator": "and",
            "conditions": [
                {"name": "knowledge_id", "comparison_operator": "is", "value": "doc-1"},
                {"name": "knowledge_id", "comparison_operator": "is", "value": "doc-2"},
            ],
        }
    )

    with pytest.raises(AdapterError, match="conflicting"):
        map_request(request)


def test_map_response_preserves_content_and_namespaces_metadata() -> None:
    mapped = map_response(
        {
            "success": True,
            "data": [
                {
                    "id": "chunk-1",
                    "content": "matched text",
                    "score": 0.9,
                    "knowledge_id": "doc-1",
                    "knowledge_title": "Guide",
                    "knowledge_filename": "guide.pdf",
                    "knowledge_source": "file",
                    "chunk_index": 3,
                    "metadata": {"page": "4"},
                    "chunk_metadata": {"question": "refund?"},
                }
            ],
        },
        knowledge_base_id="kb-1",
        top_k=5,
        score_threshold=0.5,
    )

    assert mapped.skipped_ids == []
    assert mapped.response.records[0].model_dump() == {
        "content": "matched text",
        "score": 0.9,
        "title": "Guide",
        "metadata": {
            "knowledge_base_id": "kb-1",
            "knowledge_id": "doc-1",
            "chunk_id": "chunk-1",
            "chunk_index": 3,
            "source": "file",
            "filename": "guide.pdf",
            "weknora_metadata": {"page": "4"},
            "weknora_chunk_metadata": {"question": "refund?"},
        },
    }


@pytest.mark.parametrize(
    ("title", "filename", "expected"),
    [("", "guide.pdf", "guide.pdf"), ("", "", "Untitled")],
)
def test_map_response_title_fallback(title: str, filename: str, expected: str) -> None:
    mapped = map_response(
        {
            "success": True,
            "data": [
                {
                    "id": "chunk-1",
                    "content": "text",
                    "score": 0.8,
                    "knowledge_title": title,
                    "knowledge_filename": filename,
                }
            ],
        },
        knowledge_base_id="kb-1",
        top_k=1,
        score_threshold=0,
    )

    assert mapped.response.records[0].title == expected


def test_map_response_filters_threshold_clamps_and_truncates() -> None:
    mapped = map_response(
        {
            "success": True,
            "data": [
                {"id": "too-low", "content": "low", "score": 0.4},
                {"id": "first", "content": "first", "score": 1.5},
                {"id": "second", "content": "second", "score": 0.7},
            ],
        },
        knowledge_base_id="kb-1",
        top_k=1,
        score_threshold=0.5,
    )

    assert [record.content for record in mapped.response.records] == ["first"]
    assert mapped.response.records[0].score == 1.0


@pytest.mark.parametrize("bad_score", ["0.8", True, float("nan"), float("inf")])
def test_map_response_skips_malformed_records(bad_score: object) -> None:
    mapped = map_response(
        {
            "success": True,
            "data": [
                {"id": "bad-score", "content": "secret text", "score": bad_score},
                {"id": "blank-content", "content": "  ", "score": 0.8},
            ],
        },
        knowledge_base_id="kb-1",
        top_k=5,
        score_threshold=0,
    )

    assert mapped.response.records == []
    assert mapped.skipped_ids == ["bad-score", "blank-content"]


@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"success": False, "data": []},
        {"success": True, "data": {}},
    ],
)
def test_map_response_rejects_invalid_upstream_envelope(envelope: dict[str, object]) -> None:
    with pytest.raises(AdapterError) as exc_info:
        map_response(
            envelope,
            knowledge_base_id="kb-1",
            top_k=5,
            score_threshold=0,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.error_code == "invalid_upstream_response"
