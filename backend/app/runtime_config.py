from __future__ import annotations

import os
from dataclasses import dataclass

from .graph.config import load_local_env


# Configuration defaults. Environment overrides remain supported for operators,
# but normal deployments can use these code defaults without extra settings.
DEFAULT_RAG_REQUEST_TIMEOUT_MS = 15000
DEFAULT_RAG_INDEXING_TIMEOUT_MS = 120000
DEFAULT_RAG_RETRIEVAL_TIMEOUT_MS = 10000


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false.")


def _non_negative_float(name: str, default: float = 0) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if value < 0:
        raise RuntimeError(f"{name} cannot be negative.")
    return value


@dataclass(frozen=True)
class RuntimeSettings:
    require_postgres: bool
    sql_query_database_url: str | None
    sql_pool_min_size: int
    sql_pool_max_size: int
    sql_default_page_size: int
    sql_max_page_size: int
    sql_statement_timeout_ms: int
    rag_request_timeout_ms: int
    rag_indexing_timeout_ms: int
    rag_retrieval_timeout_ms: int
    max_request_body_bytes: int
    document_search_backend: str
    document_database_url: str | None
    text_to_sql_mode: str
    text_to_sql_max_plan_cost: int
    text_to_sql_max_estimated_rows: int
    llm_input_cost_per_million_usd: float
    llm_output_cost_per_million_usd: float


def load_runtime_settings() -> RuntimeSettings:
    load_local_env()
    require_postgres = _boolean("REQUIRE_POSTGRES")
    default_page_size = _positive_int("SQL_DEFAULT_PAGE_SIZE", 50)
    max_page_size = _positive_int("SQL_MAX_PAGE_SIZE", 100)
    if default_page_size > max_page_size:
        raise RuntimeError("SQL_DEFAULT_PAGE_SIZE cannot exceed SQL_MAX_PAGE_SIZE.")
    pool_min_size = _positive_int("SQL_POOL_MIN_SIZE", 1)
    pool_max_size = _positive_int("SQL_POOL_MAX_SIZE", 10)
    if pool_min_size > pool_max_size:
        raise RuntimeError("SQL_POOL_MIN_SIZE cannot exceed SQL_POOL_MAX_SIZE.")
    database_url = os.getenv("SQL_QUERY_DATABASE_URL", "").strip() or None
    if require_postgres and database_url is None:
        raise RuntimeError(
            "SQL_QUERY_DATABASE_URL is required when REQUIRE_POSTGRES=true."
        )
    document_search_backend = (
        os.getenv("DOCUMENT_SEARCH_BACKEND", "faiss").strip().lower() or "faiss"
    )
    if document_search_backend not in {"faiss", "postgres"}:
        raise RuntimeError("DOCUMENT_SEARCH_BACKEND must be faiss or postgres.")
    document_database_url = os.getenv("DOCUMENT_DATABASE_URL", "").strip() or None
    if document_search_backend == "postgres" and document_database_url is None:
        raise RuntimeError(
            "DOCUMENT_DATABASE_URL is required when DOCUMENT_SEARCH_BACKEND=postgres."
        )
    text_to_sql_mode = os.getenv("TEXT_TO_SQL_MODE", "off").strip().lower() or "off"
    if text_to_sql_mode not in {"off", "shadow", "active"}:
        raise RuntimeError("TEXT_TO_SQL_MODE must be off, shadow, or active.")
    if text_to_sql_mode != "off" and not os.getenv("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is required when TEXT_TO_SQL_MODE is enabled.")
    if text_to_sql_mode == "active" and database_url is None:
        raise RuntimeError(
            "SQL_QUERY_DATABASE_URL is required when TEXT_TO_SQL_MODE=active."
        )
    return RuntimeSettings(
        require_postgres=require_postgres,
        sql_query_database_url=database_url,
        sql_pool_min_size=pool_min_size,
        sql_pool_max_size=pool_max_size,
        sql_default_page_size=default_page_size,
        sql_max_page_size=max_page_size,
        sql_statement_timeout_ms=_positive_int("SQL_STATEMENT_TIMEOUT_MS", 10000),
        rag_request_timeout_ms=_positive_int(
            "RAG_REQUEST_TIMEOUT_MS", DEFAULT_RAG_REQUEST_TIMEOUT_MS
        ),
        rag_indexing_timeout_ms=_positive_int(
            "RAG_INDEXING_TIMEOUT_MS", DEFAULT_RAG_INDEXING_TIMEOUT_MS
        ),
        rag_retrieval_timeout_ms=_positive_int(
            "RAG_RETRIEVAL_TIMEOUT_MS", DEFAULT_RAG_RETRIEVAL_TIMEOUT_MS
        ),
        max_request_body_bytes=_positive_int("MAX_REQUEST_BODY_BYTES", 65536),
        document_search_backend=document_search_backend,
        document_database_url=document_database_url,
        text_to_sql_mode=text_to_sql_mode,
        text_to_sql_max_plan_cost=_positive_int("TEXT_TO_SQL_MAX_PLAN_COST", 10000),
        text_to_sql_max_estimated_rows=_positive_int(
            "TEXT_TO_SQL_MAX_ESTIMATED_ROWS", 10000
        ),
        llm_input_cost_per_million_usd=_non_negative_float(
            "LLM_INPUT_COST_PER_MILLION_USD"
        ),
        llm_output_cost_per_million_usd=_non_negative_float(
            "LLM_OUTPUT_COST_PER_MILLION_USD"
        ),
    )
