from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3

from .parser import ResolvedValue, SemanticQueryParser, normalize_question


@dataclass(frozen=True)
class MaskedEntities:
    question: str
    values_by_placeholder: dict[str, tuple[tuple[str, ...], str]]
    resolved: tuple[ResolvedValue, ...]


class EntityResolver:
    """Resolve local schema values and mask them before an external planner call."""

    def __init__(self, connection: sqlite3.Connection, parser: SemanticQueryParser) -> None:
        self.connection = connection
        self.parser = parser

    def mask_question(
        self,
        question: str,
        *,
        allowed_fields: tuple[str, ...] | None = None,
    ) -> MaskedEntities:
        normalized = normalize_question(question)
        resolved = self.parser._resolve_schema_values(normalized)
        placeholders: dict[str, tuple[tuple[str, ...], str]] = {}
        masked = normalized

        values: dict[str, list[str]] = {}
        original_values: dict[str, str] = {}
        for item in resolved:
            if item.confidence == 1.0:
                normalized_value = normalize_question(item.value)
                if allowed_fields is None or item.field in allowed_fields:
                    values.setdefault(normalized_value, []).append(item.field)
                original_values[normalized_value] = item.value

        for value in sorted(values, key=len, reverse=True):
            if not value or not re.search(rf"\b{re.escape(value)}\b", masked):
                continue
            placeholder = f"<ENTITY_{len(placeholders) + 1}>"
            masked = re.sub(rf"\b{re.escape(value)}\b", placeholder, masked, count=1)
            placeholders[placeholder] = (tuple(dict.fromkeys(values[value])), original_values[value])

        # Mask identifier-shaped values even when the ID is not present in the database.
        for pattern, field in (
            (r"\binv\d{4}\b", "invoices.invoice_id"),
            (r"\bpo\d{4}\b", "invoices.po_id"),
            (r"\bpr\d{3}\b", "invoices.project_id"),
            (r"\bp\d{3}\b", "properties.property_id"),
            (r"\bv\d{3}\b", "vendors.vendor_id"),
            (r"\bcc\d{3}\b", "budgets.cost_code"),
            (r"\bb\d{4}\b", "budgets.budget_id"),
            (r"\bpay\d{4}\b", "payments.payment_id"),
            (r"\b[A-Z]{5}\d{4}[A-Z]\b", "vendors.tax_id"),
            (r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b", "vendors.tax_id"),
        ):
            for match in tuple(re.finditer(pattern, masked, re.IGNORECASE)):
                placeholder = f"<ENTITY_{len(placeholders) + 1}>"
                value = match.group(0).upper()
                masked = masked.replace(match.group(0), placeholder, 1)
                placeholder_fields = (field,) if allowed_fields is None or field in allowed_fields else ()
                placeholders[placeholder] = (placeholder_fields, value)

        for pattern in (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", r"(?<!\w)\+?\d[\d ().-]{8,}\d(?!\w)"):
            for match in tuple(re.finditer(pattern, masked, re.IGNORECASE)):
                placeholder = f"<ENTITY_{len(placeholders) + 1}>"
                value = match.group(0)
                masked = masked.replace(value, placeholder, 1)
                placeholders[placeholder] = ((), value)

        masked = self._mask_unresolved_named_values(
            masked,
            placeholders,
            allowed_fields=allowed_fields,
        )

        return MaskedEntities(
            question=masked,
            values_by_placeholder=placeholders,
            resolved=resolved,
        )

    def _mask_unresolved_named_values(
        self,
        question: str,
        placeholders: dict[str, tuple[tuple[str, ...], str]],
        *,
        allowed_fields: tuple[str, ...] | None,
    ) -> str:
        masked = question
        stops = r"in|with|having|that|which|whose|where|without|and|no|has|have|is|are|on|to|from|by|at|for|against|show|list|located|invoice|invoices|budget|budgets|property|properties|vendor|vendors|name|names|id|city|status|type|category|amount"
        patterns = (
            (rf"\b(?:property|properties)\s+(?:named\s+|called\s+)?((?!(?:{stops})\b)[a-z0-9]+(?:\s+(?!(?:{stops})\b)[a-z0-9]+){{0,3}}?)(?=\s+(?:{stops})\b|$)", "properties.property_name"),
            (rf"\b(?:vendor|vendors|supplier|suppliers)\s+(?:named\s+|called\s+)?((?!(?:{stops})\b)[a-z0-9]+(?:\s+(?!(?:{stops})\b)[a-z0-9]+){{0,3}}?)(?=\s+(?:{stops})\b|$)", "vendors.vendor_name"),
        )
        for pattern, field in patterns:
            match = re.search(pattern, masked)
            if match is None:
                continue
            value = match.group(1).strip()
            if value.startswith("<entity_") or value in {"named", "called"}:
                continue
            placeholder = f"<ENTITY_{len(placeholders) + 1}>"
            masked = masked[:match.start(1)] + placeholder + masked[match.end(1):]
            placeholder_fields = (
                (field,)
                if allowed_fields is None or field in allowed_fields
                else ()
            )
            placeholders[placeholder] = (placeholder_fields, value)
        return masked

    def restore_plan_values(
        self,
        plan_data: dict[str, object],
        values_by_placeholder: dict[str, tuple[tuple[str, ...], str]],
    ) -> dict[str, object]:
        restored = dict(plan_data)
        raw_filters = restored.get("filters", ())
        if not isinstance(raw_filters, list):
            return restored

        restored_filters: list[dict[str, object]] = []
        for raw_filter in raw_filters:
            if not isinstance(raw_filter, dict):
                return restored
            item = dict(raw_filter)
            value = item.get("value")
            if isinstance(value, str) and value in values_by_placeholder:
                resolved_fields, actual_value = values_by_placeholder[value]
                if item.get("field") not in resolved_fields:
                    raise ValueError("An entity placeholder was applied to the wrong schema field.")
                item["value"] = actual_value
            restored_filters.append(item)
        restored["filters"] = restored_filters
        return restored
