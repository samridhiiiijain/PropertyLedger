from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .catalog import OBJECTS
from .schema_context import SelectedSchema


class PlannerUnavailable(RuntimeError):
    def __init__(self, message: str, *, category: str = "unavailable") -> None:
        super().__init__(message)
        self.category = category


class PlannerUnsupported(RuntimeError):
    pass


class PlannerInvalidResponse(RuntimeError):
    pass


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


class GeminiQueryPlanner:
    """Ask Gemini for a constrained query plan; never request or accept SQL."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)).strip()

    def plan(
        self,
        *,
        masked_question: str,
        schema: SelectedSchema,
        entity_placeholders: tuple[dict[str, str], ...],
        repair_issues: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if not self.api_key:
            raise PlannerUnavailable("Gemini fallback is enabled but GEMINI_API_KEY is not configured.")

        catalog = {
            "objects": [
                {
                    "name": name,
                    "table": OBJECTS[name].table,
                    "fields": OBJECTS[name].allowed_fields,
                }
                for name in schema.objects
            ],
            "allowed_filter_and_return_fields": schema.fields,
            "approved_metrics": schema.metric_definitions,
            "business_definitions": schema.definitions,
            "resolved_entity_placeholders": entity_placeholders,
        }
        plan_shape = {
            "object": "one selected object name",
            "filters": [{"field": "approved field", "operator": "=", "value": "literal or entity placeholder"}],
            "conditions": [{"metric": "approved metric", "operator": "=", "value": 0}],
            "aggregations": [{"function": "count or sum", "field": "approved field or null", "alias": "simple alias"}],
            "group_by": ["approved field"],
            "return_fields": ["approved field"],
            "sort": [{"field": "approved field", "direction": "asc or desc"}],
            "limit": 50,
        }
        repair = ""
        if repair_issues:
            repair = "\nThe previous plan was rejected for these reasons. Return a corrected plan only: " + json.dumps(repair_issues)
        prompt = (
            "Interpret the business question and return exactly one JSON object matching the requested query-plan shape. "
            "Do not return SQL, explanations, markdown, new tables, fields, metrics, joins, IDs, or business definitions. "
            "Use only the supplied catalog. Use entity placeholder tokens exactly as filter values and only with one of their listed fields. "
            "If the request cannot be expressed with this catalog, return {\"unsupported\":true}. "
            "Never infer a client identifier or invent a filter. A missing filter must stay missing only when the question truly has no such constraint. "
            "For row filtering by an approved metric, represent it as a condition using that metric. "
            "For a singular top, highest, lowest, most, least, largest, or smallest request, return one row, sort by the requested approved measure, and include that measure in return_fields. "
            f"\nMasked question: {masked_question}"
            f"\nSelected schema and business definitions: {json.dumps(catalog, ensure_ascii=True)}"
            f"\nRequired plan shape: {json.dumps(plan_shape)}"
            f"{repair}"
        )
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
                    "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
                },
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlannerUnavailable(
                "Gemini planner request failed.",
                category=provider_error_category(exc),
            ) from exc

        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            if not isinstance(result, dict):
                raise PlannerInvalidResponse("Planner response must be a JSON object.")
            if result.get("unsupported") is True:
                raise PlannerUnsupported("The question is not supported by the selected schema.")
            if "sql" in result or "query" in result:
                raise PlannerInvalidResponse("Planner returned a query string instead of a query plan.")
            return result
        except PlannerUnsupported:
            raise
        except PlannerInvalidResponse:
            raise
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise PlannerInvalidResponse("Gemini returned a malformed query-plan response.") from exc


def provider_error_category(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "authentication"
        if status == 429:
            return "rate_limited"
        if status >= 500:
            return "provider_server_error"
        return "provider_http_error"
    if isinstance(exc, httpx.RequestError):
        return "network"
    return "unavailable"
