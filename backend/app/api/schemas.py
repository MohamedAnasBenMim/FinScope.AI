from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator

DocumentType = Literal["invoice", "devis", "bilan", "other"]


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000, validation_alias=AliasChoices("question", "query"))
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    document_types: list[DocumentType] = Field(default_factory=list, max_length=4)
    debug: bool = False

    @field_validator("question")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank.")
        return value.strip()


class CalculateRequest(BaseModel):
    calc_type: Literal["yoy", "margin"]
    param1: str | float
    param2: str | float
    metric_name: str = Field("Metric", max_length=100)
