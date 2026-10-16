from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import ConfigDict, Field

from ..models import FrozenModel


class QueryStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class QueryFilter(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    operator: Literal["=", "!=", ">", "<", ">=", "<=", "in"]
    value: str | int | float
    confidence: float = Field(ge=0, le=1)


class QueryCondition(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    operator: Literal["=", "!=", ">", "<", ">=", "<="]
    value: str | int | float
    confidence: float = Field(ge=0, le=1)


class QuerySort(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    direction: Literal["asc", "desc"] = "asc"


class QueryAggregation(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    function: Literal["count", "sum"]
    field: str | None = None
    alias: str
    confidence: float = Field(ge=0, le=1)


class QueryPlan(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    object: Literal["property", "invoice", "vendor", "budget", "payment", "purchase_order"]
    filters: tuple[QueryFilter, ...] = ()
    conditions: tuple[QueryCondition, ...] = ()
    aggregations: tuple[QueryAggregation, ...] = ()
    group_by: tuple[str, ...] = ()
    return_fields: tuple[str, ...]
    sort: tuple[QuerySort, ...] = ()
    limit: int = Field(default=50, ge=1, le=100)
    confidence: float = Field(ge=0, le=1)
    normalized_question: str
    unresolved_terms: tuple[str, ...] = ()


class QueryValidationResult(FrozenModel):
    is_valid: bool
    message: str
    issues: tuple[str, ...] = ()


class SemanticQueryResponse(FrozenModel):
    question: str
    status: QueryStatus
    answer: str
    plan: QueryPlan | None = None
    validation: QueryValidationResult | None = None
    rows: tuple[dict[str, Any], ...] = ()
    evidence: tuple[str, ...] = ()
    sql: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_successful(self) -> bool:
        return self.status in {QueryStatus.OK, QueryStatus.EMPTY, QueryStatus.ANSWERED}


class SemanticQueryPublicResponse(FrozenModel):
    question: str
    status: QueryStatus
    answer: str
    rows: tuple[dict[str, Any], ...] = ()
    evidence: tuple[str, ...] = ()


class SemanticQueryRequest(FrozenModel):
    question: str = Field(min_length=4, max_length=300)
    limit: int | None = Field(default=None, ge=1, le=1000)
