"""Validated Dify and WeKnora wire models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)


class RetrievalSetting(StrictModel):
    top_k: int = Field(ge=1, le=100)
    score_threshold: float = Field(ge=0, le=1)


MetadataScalar = str | int | float
MetadataValue = MetadataScalar | list[MetadataScalar] | None


class MetadataFilter(StrictModel):
    name: str
    comparison_operator: str
    value: MetadataValue = None


class MetadataCondition(StrictModel):
    logical_operator: str = "and"
    conditions: list[MetadataFilter] = Field(default_factory=list)


class DifyRetrievalRequest(StrictModel):
    knowledge_id: str
    query: str
    retrieval_setting: RetrievalSetting
    metadata_condition: MetadataCondition | None = None

    @field_validator("knowledge_id", "query")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DifyRecord(StrictModel):
    content: str
    score: float
    title: str
    metadata: dict[str, Any]


class DifyRetrievalResponse(StrictModel):
    records: list[DifyRecord]
