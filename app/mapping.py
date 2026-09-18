"""Pure mappings between Dify and WeKnora contracts."""

import math
from dataclasses import dataclass
from typing import Any

from app.errors import AdapterError
from app.models import (
    DifyRecord,
    DifyRetrievalRequest,
    DifyRetrievalResponse,
    MetadataFilter,
)


@dataclass(frozen=True, slots=True)
class MappedRequest:
    knowledge_base_id: str
    payload: dict[str, Any]
    short_circuit_empty: bool = False


@dataclass(frozen=True, slots=True)
class MappedResponse:
    response: DifyRetrievalResponse
    skipped_ids: list[str]


def _unsupported(message: str) -> AdapterError:
    return AdapterError(400, "unsupported_metadata_condition", message)


def _string_values(condition: MetadataFilter) -> list[str]:
    value = condition.value
    if condition.comparison_operator == "is":
        if not isinstance(value, str) or not value.strip():
            raise _unsupported(f"metadata field '{condition.name}' requires a string value")
        return [value]
    if condition.comparison_operator == "in":
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            raise _unsupported(
                f"metadata field '{condition.name}' requires a non-empty string list"
            )
        return list(dict.fromkeys(value))
    raise _unsupported(
        f"comparison operator '{condition.comparison_operator}' is not supported "
        f"for metadata field '{condition.name}'"
    )


def _merge_single_filter(
    current: list[str] | None,
    incoming: list[str],
    field_name: str,
) -> list[str]:
    if current is None or current == incoming:
        return incoming
    raise _unsupported(f"conflicting metadata conditions for '{field_name}'")


def map_request(request: DifyRetrievalRequest) -> MappedRequest:
    """Map one validated Dify request to a WeKnora hybrid-search request."""

    payload: dict[str, Any] = {
        "query_text": request.query.strip(),
        "match_count": request.retrieval_setting.top_k,
        "vector_threshold": request.retrieval_setting.score_threshold,
        "disable_keywords_match": True,
        "disable_vector_match": False,
    }
    short_circuit_empty = False
    knowledge_ids: list[str] | None = None
    tag_ids: list[str] | None = None

    metadata_condition = request.metadata_condition
    if metadata_condition is not None:
        if metadata_condition.logical_operator != "and":
            raise _unsupported(
                f"logical operator '{metadata_condition.logical_operator}' is not supported"
            )
        for condition in metadata_condition.conditions:
            if condition.name == "knowledge_base_id":
                if condition.comparison_operator != "is":
                    raise _unsupported(
                        "metadata field 'knowledge_base_id' supports only the 'is' operator"
                    )
                values = _string_values(condition)
                if values[0] != request.knowledge_id:
                    short_circuit_empty = True
            elif condition.name == "knowledge_id":
                values = _string_values(condition)
                knowledge_ids = _merge_single_filter(knowledge_ids, values, "knowledge_id")
            elif condition.name in {"tag_id", "tag_ids"}:
                values = _string_values(condition)
                tag_ids = _merge_single_filter(tag_ids, values, "tag_ids")
            else:
                raise _unsupported(f"metadata field '{condition.name}' is not supported")

    if knowledge_ids:
        payload["knowledge_ids"] = knowledge_ids
    if tag_ids:
        payload["tag_ids"] = tag_ids

    return MappedRequest(
        knowledge_base_id=request.knowledge_id.strip(),
        payload=payload,
        short_circuit_empty=short_circuit_empty,
    )


def _safe_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _safe_identifier(item: dict[str, Any]) -> str:
    value = item.get("id")
    if isinstance(value, str) and value:
        return value
    return "unknown"


def map_response(
    envelope: dict[str, Any],
    *,
    knowledge_base_id: str,
    top_k: int,
    score_threshold: float,
) -> MappedResponse:
    """Map a WeKnora result envelope into Dify records."""

    data = envelope.get("data")
    if envelope.get("success") is not True or not isinstance(data, list):
        raise AdapterError(
            502,
            "invalid_upstream_response",
            "WeKnora returned an invalid response envelope",
        )

    records: list[DifyRecord] = []
    skipped_ids: list[str] = []
    for raw_item in data:
        if not isinstance(raw_item, dict):
            skipped_ids.append("unknown")
            continue
        item = {str(key): value for key, value in raw_item.items()}
        content = item.get("content")
        raw_score = item.get("score")
        if (
            not isinstance(content, str)
            or not content.strip()
            or isinstance(raw_score, bool)
            or not isinstance(raw_score, (int, float))
            or not math.isfinite(float(raw_score))
        ):
            skipped_ids.append(_safe_identifier(item))
            continue

        score = min(1.0, max(0.0, float(raw_score)))
        if score < score_threshold:
            continue

        title_value = item.get("knowledge_title")
        filename_value = item.get("knowledge_filename")
        title = title_value.strip() if isinstance(title_value, str) else ""
        filename = filename_value.strip() if isinstance(filename_value, str) else ""
        title = title or filename or "Untitled"

        records.append(
            DifyRecord(
                content=content,
                score=score,
                title=title,
                metadata={
                    "knowledge_base_id": knowledge_base_id,
                    "knowledge_id": item.get("knowledge_id", ""),
                    "chunk_id": item.get("id", ""),
                    "chunk_index": item.get("chunk_index", 0),
                    "source": item.get("knowledge_source", ""),
                    "filename": filename,
                    "weknora_metadata": _safe_mapping(item.get("metadata")),
                    "weknora_chunk_metadata": _safe_mapping(item.get("chunk_metadata")),
                },
            )
        )
        if len(records) >= top_k:
            break

    return MappedResponse(
        response=DifyRetrievalResponse(records=records),
        skipped_ids=skipped_ids,
    )
