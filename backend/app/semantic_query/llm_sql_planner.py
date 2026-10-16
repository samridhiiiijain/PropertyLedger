from __future__ import annotations

import json
import os
from typing import Any, Callable

import httpx

from .llm_planner import (
    DEFAULT_GEMINI_MODEL,
    PlannerInvalidResponse,
    PlannerUnavailable,
    provider_error_category,
)
from .catalog import FIELD_EXPRESSIONS, FIELD_RESULT_ALIASES, OBJECTS, TABLE_ALIASES
from .schema_context import SelectedSchema


SQL_PROMPT_VERSION = "2026-10-09-v1"


class GeminiSqlPlanner:
    """Request SQL structure only; parameter values never cross this boundary."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        usage_recorder: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)).strip()
        self.usage_recorder = usage_recorder

    def propose(
        self,
        *,
        masked_question: str,
        schema: SelectedSchema,
        placeholder_contract: tuple[dict[str, Any], ...],
        intent_contract: dict[str, Any],
        approved_joins: tuple[str, ...],
        repair_issue: str | None = None,
    ) -> str:
        if not self.api_key:
            raise PlannerUnavailable("Gemini SQL generation is enabled but GEMINI_API_KEY is not configured.")

        physical_schema = {
            "objects": {
                name: {"table": OBJECTS[name].table, "alias": OBJECTS[name].alias}
                for name in schema.objects
            },
            "fields": {
                field: {
                    "sql": FIELD_EXPRESSIONS.get(
                        field,
                        f"{TABLE_ALIASES[field.split('.', 1)[0]]}.{field.split('.', 1)[1]}",
                    ),
                    "result_alias": FIELD_RESULT_ALIASES.get(
                        field, field.split(".", 1)[1]
                    ),
                }
                for field in schema.fields
            },
        }
        prompt = (
            "Return exactly one JSON object with one key named sql. The sql value must be one read-only SELECT. "
            "Use only the supplied tables, fields, approved joins, and named placeholders. "
            "The validated intent contract contains required physical SELECT, WHERE, GROUP BY, and ORDER BY clauses. "
            "Reproduce every non-empty required clause exactly; only whitespace and SQL keyword case may differ. "
            "Do not include LIMIT; the backend adds it. Do not include comments, semicolons, CTEs, UNION, SELECT *, "
            "system schemas, literal user values, or additional filters. Every supplied placeholder must occur exactly "
            "where its field and operator contract requires it. Preserve the requested output fields and aliases. "
            "Never infer or invent identifiers."
            f"\nPrompt version: {SQL_PROMPT_VERSION}"
            f"\nMasked question: {masked_question}"
            f"\nPhysical schema: {json.dumps(physical_schema, ensure_ascii=True)}"
            f"\nApproved metrics: {json.dumps(schema.metric_definitions, ensure_ascii=True)}"
            f"\nPlaceholder contract: {json.dumps(placeholder_contract, ensure_ascii=True)}"
            f"\nValidated intent contract: {json.dumps(intent_contract, ensure_ascii=True)}"
            f"\nApproved joins: {json.dumps(approved_joins, ensure_ascii=True)}"
        )
        if repair_issue:
            prompt += f"\nThe previous proposal had this non-sensitive semantic error: {repair_issue}. Return one corrected proposal."

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            response = httpx.post(
                url,
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlannerUnavailable(
                "Gemini SQL generation request failed.",
                category=provider_error_category(exc),
            ) from exc

        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            usage = body.get("usageMetadata", {})
            if self.usage_recorder is not None and isinstance(usage, dict):
                self.usage_recorder(
                    self.model,
                    _usage_count(usage, "promptTokenCount"),
                    _usage_count(usage, "candidatesTokenCount"),
                    _usage_count(usage, "totalTokenCount"),
                )
            result = json.loads(text)
            if not isinstance(result, dict) or set(result) != {"sql"}:
                raise PlannerInvalidResponse("SQL proposal must contain only the sql field.")
            sql = result["sql"]
            if not isinstance(sql, str) or not sql.strip():
                raise PlannerInvalidResponse("SQL proposal must be a non-empty string.")
            return sql.strip()
        except PlannerInvalidResponse:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise PlannerInvalidResponse("Gemini returned a malformed SQL proposal.") from exc


def _usage_count(usage: dict[str, Any], name: str) -> int:
    value = usage.get(name, 0)
    return int(value) if isinstance(value, (int, float)) and value >= 0 else 0
