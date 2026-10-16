from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
import re
import sqlite3

from ..database import create_connection
from .catalog import ABBREVIATIONS, METRICS, OBJECTS, VALUE_LOOKUP_FIELDS
from .models import QueryAggregation, QueryCondition, QueryFilter, QueryPlan, QuerySort


class AmbiguousEntityError(ValueError):
    def __init__(self, field: str, values: tuple[str, ...]) -> None:
        self.field = field
        self.values = values
        super().__init__(f"Multiple values matched {field}: {', '.join(values)}")


@dataclass(frozen=True)
class ResolvedValue:
    field: str
    value: str
    confidence: float


@dataclass(frozen=True)
class ConfidenceAssessment:
    object_match: float
    metric_match: float
    filter_match: float
    operator_match: float
    plan_completeness: float

    @property
    def score(self) -> float:
        return round(
            0.25 * self.object_match
            + 0.25 * self.metric_match
            + 0.20 * self.filter_match
            + 0.15 * self.operator_match
            + 0.15 * self.plan_completeness,
            2,
        )


def normalize_question(question: str) -> str:
    normalized = question.strip().lower()
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = re.sub(r"(?<=\d)\.(?=\d)", "qdecimalq", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = normalized.replace("qdecimalq", ".")
    words = [ABBREVIATIONS.get(word, word) for word in normalized.split()]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


class SemanticQueryParser:
    def __init__(self, connection: sqlite3.Connection | None) -> None:
        # Direct parser callers may not have an application-managed connection.
        # Keep that use case compatible with the local structured-data fallback;
        # request handling still supplies its pooled connection explicitly.
        self.connection = connection or create_connection()

    def parse(self, question: str) -> QueryPlan | None:
        normalized = normalize_question(question)
        object_name, object_confidence = self._detect_object(normalized)
        if object_name is None:
            return None

        conditions = self._detect_conditions(normalized, object_name)
        filters = self._detect_filters(normalized, object_name, conditions)
        aggregations = self._detect_aggregations(normalized, object_name)
        group_by = self._detect_group_by(normalized, object_name, aggregations)
        has_intent = self._has_query_intent(normalized, filters, conditions, aggregations)
        if not has_intent:
            return None
        confidence = self._confidence(
            normalized,
            object_confidence,
            filters,
            conditions,
            aggregations,
            group_by,
            has_intent,
        )
        query_object = OBJECTS[object_name]
        sort_field_by_object = {
            "invoice": "invoices.invoice_id",
            "budget": "budgets.cost_code",
            "property": "properties.property_name",
            "vendor": "vendors.vendor_name",
            "purchase_order": "purchase_orders.po_id",
            "payment": "payments.payment_id",
        }
        sort = () if aggregations else (
            QuerySort(field=sort_field_by_object.get(object_name, query_object.default_fields[0]), direction="asc"),
        )
        if aggregations:
            return_fields = group_by
        else:
            return_fields = query_object.default_fields

        return QueryPlan(
            object=object_name,
            filters=filters,
            conditions=conditions,
            aggregations=aggregations,
            group_by=group_by,
            return_fields=return_fields,
            sort=sort,
            limit=50,
            confidence=confidence,
            normalized_question=normalized,
            unresolved_terms=(),
        )

    def _detect_object(self, normalized: str) -> tuple[str | None, float]:
        if self._contains_phrase(normalized, "reconciliation"):
            return "invoice", 1.0
        if self._asks_for_count(normalized) and self._contains_phrase(normalized, "by vendor"):
            return "invoice", 1.0
        if self._asks_for_count(normalized) and self._contains_phrase(normalized, "by property"):
            return "invoice", 1.0
        if self._mentions_po_variance(normalized):
            return "invoice", 1.0
        if self._mentions_budget_variance(normalized):
            return "budget", 1.0

        words = normalized.split()
        best_name: str | None = None
        best_score = 0.0

        for name, query_object in OBJECTS.items():
            for synonym in query_object.synonyms:
                score = 1.0 if self._contains_phrase(normalized, synonym) else 0.0
                if score == 0.0:
                    close_matches = get_close_matches(synonym, words, n=1, cutoff=0.82)
                    score = 0.78 if close_matches else 0.0
                if score > best_score:
                    best_name = name
                    best_score = score

        return best_name, best_score

    def _detect_filters(
        self,
        normalized: str,
        object_name: str,
        conditions: tuple[QueryCondition, ...],
    ) -> tuple[QueryFilter, ...]:
        resolved = self._resolve_schema_values(normalized)
        allowed_prefixes = self._allowed_filter_prefixes(object_name)
        metric_names = {condition.metric for condition in conditions}
        entity_filters = tuple(
            QueryFilter(
                field=item.field,
                operator="=",
                value=item.value,
                confidence=item.confidence,
            )
            for item in resolved
            if any(item.field.startswith(prefix) for prefix in allowed_prefixes)
            and not (
                object_name == "invoice"
                and item.field == "vendors.city"
                and not self._mentions_vendor_context(normalized)
            )
            and not (
                "unpaid_invoice" in metric_names
                and item.field == "invoices.status"
            )
        )
        entity_filters = self._prefer_base_table_identifiers(entity_filters, object_name)
        scalar_filters = self._detect_scalar_comparisons(normalized, object_name)
        return (*entity_filters, *scalar_filters)

    def _prefer_base_table_identifiers(
        self,
        filters: tuple[QueryFilter, ...],
        object_name: str,
    ) -> tuple[QueryFilter, ...]:
        base_table = OBJECTS[object_name].table
        grouped: dict[tuple[str, str], list[QueryFilter]] = {}
        retained: list[QueryFilter] = []
        for item in filters:
            column = item.field.split(".", 1)[1]
            if not column.endswith("_id"):
                retained.append(item)
                continue
            grouped.setdefault((column, str(item.value).casefold()), []).append(item)
        for items in grouped.values():
            preferred = next(
                (item for item in items if item.field.startswith(f"{base_table}.")),
                items[0],
            )
            retained.append(preferred)
        return tuple(retained)

    def _detect_scalar_comparisons(
        self,
        normalized: str,
        object_name: str,
    ) -> tuple[QueryFilter, ...]:
        fields = {
            "invoice": (
                ("invoice amount", "invoices.invoice_amount"),
                ("paid amount", "invoices.paid_amount"),
                ("outstanding amount", "invoices.outstanding_amount"),
                ("amount", "invoices.invoice_amount"),
            ),
            "budget": (
                ("budget amount", "budgets.budget_amount"),
                ("committed amount", "budgets.committed_amount"),
                ("actual amount", "budgets.actual_amount"),
                ("remaining budget", "budgets.remaining_budget"),
                ("amount", "budgets.budget_amount"),
            ),
            "purchase_order": (
                ("purchase order total", "purchase_orders.po_total"),
                ("po total", "purchase_orders.po_total"),
                ("amount", "purchase_orders.po_total"),
            ),
            "payment": (
                ("payment amount", "payments.amount"),
                ("amount", "payments.amount"),
            ),
        }.get(object_name, ())
        if not fields:
            return ()

        operators = (
            ("greater than", ">"),
            ("more than", ">"),
            ("at least", ">="),
            ("less than", "<"),
            ("at most", "<="),
            ("above", ">"),
            ("below", "<"),
            ("over", ">"),
            ("under", "<"),
            ("equal to", "="),
            ("equals", "="),
        )
        field_pattern = "|".join(re.escape(label) for label, _field in fields)
        operator_pattern = "|".join(re.escape(label) for label, _operator in operators)
        match = re.search(
            rf"\b(?:(?P<field>{field_pattern})\s+)?(?P<operator>{operator_pattern})\s+(?P<amount>\d+(?:\s\d{{3}})*(?:\.\d+)?)\b",
            normalized,
        )
        if match is None:
            return ()
        field_label = match.group("field") or "amount"
        field = dict(fields)[field_label]
        operator = dict(operators)[match.group("operator")]
        amount_text = match.group("amount").replace(" ", "")
        value: int | float = float(amount_text) if "." in amount_text else int(amount_text)
        return (
            QueryFilter(
                field=field,
                operator=operator,
                value=value,
                confidence=1.0,
            ),
        )

    def _allowed_filter_prefixes(self, object_name: str) -> tuple[str, ...]:
        if object_name == "invoice":
            return ("invoices.", "properties.", "vendors.")
        if object_name == "vendor":
            return ("vendors.",)
        if object_name == "budget":
            return ("budgets.",)
        if object_name == "purchase_order":
            return ("purchase_orders.", "properties.", "vendors.")
        if object_name == "payment":
            return ("payments.", "invoices.", "properties.", "vendors.")
        return (f"{OBJECTS[object_name].table}.",)

    def _resolve_schema_values(self, normalized: str) -> tuple[ResolvedValue, ...]:
        candidates: list[ResolvedValue] = []
        candidates.extend(self._stable_identifier_values(normalized))
        for field in VALUE_LOOKUP_FIELDS:
            table, column = field.split(".", 1)
            rows = self.connection.execute(
                f"SELECT DISTINCT {column} AS value FROM {table} ORDER BY {column}"
            ).fetchall()
            for row in rows:
                # Support both sqlite.Row connections and plain tuple rows.
                # Some callers provide an externally-created connection without
                # the row factory used by create_connection().
                if isinstance(row, (sqlite3.Row, dict)):
                    value = str(row["value"])
                else:
                    value = str(row[0])
                normalized_value = normalize_question(value)
                if self._contains_phrase(normalized, normalized_value):
                    candidates.append(ResolvedValue(field=field, value=value, confidence=1.0))
                elif not self._is_stable_identifier(value) and self._close_phrase(normalized, normalized_value):
                    candidates.append(ResolvedValue(field=field, value=value, confidence=0.76))

        resolved = self._dedupe_resolved_values(candidates)
        exact_by_field: dict[str, set[str]] = {}
        for item in resolved:
            if item.confidence == 1.0:
                exact_by_field.setdefault(item.field, set()).add(item.value)
        for field, values in exact_by_field.items():
            if len(values) > 1 and field in {
                "properties.property_name",
                "vendors.vendor_name",
                "properties.city",
                "vendors.city",
            }:
                raise AmbiguousEntityError(field, tuple(sorted(values)))
        return resolved

    def _stable_identifier_values(self, normalized: str) -> list[ResolvedValue]:
        values: list[ResolvedValue] = []
        for pattern, field in (
            (r"\binv\d{4}\b", "invoices.invoice_id"),
            (r"\bpr\d{3}\b", "invoices.project_id"),
            (r"\bpr\d{3}\b", "budgets.project_id"),
            (r"\bpr\d{3}\b", "properties.project_id"),
            (r"\bp\d{3}\b", "invoices.property_id"),
            (r"\bp\d{3}\b", "budgets.property_id"),
            (r"\bv\d{3}\b", "invoices.vendor_id"),
            (r"\bv\d{3}\b", "vendors.vendor_id"),
            (r"\bcc\d{3}\b", "budgets.cost_code"),
        ):
            for match in re.finditer(pattern, normalized):
                values.append(
                    ResolvedValue(
                        field=field,
                        value=match.group(0).upper(),
                        confidence=1.0,
                    )
                )
        return values

    def _detect_conditions(
        self,
        normalized: str,
        object_name: str,
    ) -> tuple[QueryCondition, ...]:
        conditions: list[QueryCondition] = []
        for metric in METRICS.values():
            if metric.base_object != object_name:
                continue
            matched = any(self._contains_phrase(normalized, synonym) for synonym in metric.synonyms)
            if not matched:
                continue
            operator = ">"
            value = 0
            if metric.kind == "row_filter":
                operator = "="
                value = 1
            elif (
                self._contains_phrase(normalized, "no unpaid")
                or self._contains_phrase(normalized, "without unpaid")
                or self._contains_phrase(normalized, "zero unpaid")
            ):
                operator = "="
            conditions.append(
                QueryCondition(
                    metric=metric.name,
                    operator=operator,
                    value=value,
                    confidence=1.0,
                )
            )
        return tuple(conditions)

    def _detect_aggregations(
        self,
        normalized: str,
        object_name: str,
    ) -> tuple[QueryAggregation, ...]:
        if self._asks_for_count(normalized):
            return (
                QueryAggregation(
                    function="count",
                    field=None,
                    alias=f"{object_name}_count",
                    confidence=1.0,
                ),
            )

        if object_name == "invoice" and (
            self._contains_phrase(normalized, "total outstanding")
            or self._contains_phrase(normalized, "outstanding amount")
            or self._contains_phrase(normalized, "outstanding balance")
        ):
            return (
                QueryAggregation(
                    function="sum",
                    field="invoices.outstanding_amount",
                    alias="total_outstanding_amount",
                    confidence=1.0,
                ),
            )

        return ()

    def _detect_group_by(
        self,
        normalized: str,
        object_name: str,
        aggregations: tuple[QueryAggregation, ...],
    ) -> tuple[str, ...]:
        if not aggregations:
            return ()

        if object_name == "vendor" or self._contains_phrase(normalized, "by vendor"):
            return ("vendors.vendor_id", "vendors.vendor_name")

        if object_name == "property" or self._contains_phrase(normalized, "by property"):
            return ("properties.property_id", "properties.property_name")

        return ()

    def _asks_for_count(self, normalized: str) -> bool:
        count_phrases = (
            "how many",
            "count",
            "number of",
            "no of",
            "total number of",
        )
        return any(self._contains_phrase(normalized, phrase) for phrase in count_phrases)

    def _mentions_vendor_context(self, normalized: str) -> bool:
        return any(
            self._contains_phrase(normalized, phrase)
            for phrase in ("vendor", "vendors", "supplier", "contractor")
        )

    def _mentions_po_variance(self, normalized: str) -> bool:
        return any(
            self._contains_phrase(normalized, phrase)
            for phrase in (
                "po variance",
                "purchase order variance",
                "invoice over po",
                "invoice exceeds po",
                "invoice amount greater than po amount",
                "invoice amounts greater than po amounts",
                "over purchase order",
            )
        )

    def _mentions_budget_variance(self, normalized: str) -> bool:
        return any(
            self._contains_phrase(normalized, phrase)
            for phrase in (
                "cost code over budget",
                "cost codes over budget",
                "budget variance",
                "budget variances",
                "above budget",
                "over budget",
            )
        )

    def _confidence(
        self,
        normalized: str,
        object_confidence: float,
        filters: tuple[QueryFilter, ...],
        conditions: tuple[QueryCondition, ...],
        aggregations: tuple[QueryAggregation, ...],
        group_by: tuple[str, ...],
        has_intent: bool,
    ) -> float:
        requested_comparison = self._requests_comparison(normalized)
        requested_metric = any(
            self._contains_phrase(normalized, phrase)
            for metric in METRICS.values()
            for phrase in metric.synonyms
        ) or self._mentions_po_variance(normalized) or self._mentions_budget_variance(normalized)
        comparison_filters = tuple(item for item in filters if item.operator != "=")
        metric_match = (
            min((item.confidence for item in conditions), default=0.0)
            if requested_metric
            else min((item.confidence for item in comparison_filters), default=0.0)
            if requested_comparison
            else 1.0
        )
        requested_filter = self._requests_filter(normalized)
        filter_match = (
            min(
                (item.confidence for item in filters),
                default=1.0 if group_by else 0.0,
            )
            if requested_filter
            else 1.0
        )
        requested_operator = requested_comparison
        operator_match = (
            min(
                (
                    item.confidence
                    for item in conditions
                    if METRICS[item.metric].comparison_predicate
                ),
                default=min(
                    (item.confidence for item in comparison_filters),
                    default=0.0,
                ),
            )
            if requested_operator
            else 1.0
        )
        completeness = float(
            object_confidence > 0
            and has_intent
            and (not requested_metric or bool(conditions))
            and (
                not requested_operator
                or any(METRICS[item.metric].comparison_predicate for item in conditions)
                or bool(comparison_filters)
            )
            and (not requested_filter or bool(filters or group_by))
            and bool(aggregations or conditions or filters or has_intent)
        )
        return ConfidenceAssessment(
            object_match=object_confidence,
            metric_match=metric_match,
            filter_match=filter_match,
            operator_match=operator_match,
            plan_completeness=completeness,
        ).score

    def _requests_filter(self, normalized: str) -> bool:
        return any(
            self._contains_phrase(normalized, phrase)
            for phrase in (
                "in", "at", "located in", "city", "named", "called", "with",
                "for", "project", "vendor", "property id", "invoice id", "status",
            )
        )

    def _requests_comparison(self, normalized: str) -> bool:
        return any(
            self._contains_phrase(normalized, phrase)
            for phrase in (
                "greater than", "more than", "less than", "above", "below",
                "over", "under", "at least", "at most", "equals", "equal to",
            )
        )

    def _has_query_intent(
        self,
        normalized: str,
        filters: tuple[QueryFilter, ...],
        conditions: tuple[QueryCondition, ...],
        aggregations: tuple[QueryAggregation, ...],
    ) -> bool:
        request_phrases = (
            "show", "list", "which", "what", "find", "get", "display", "give",
            "tell", "report", "explain", "how many", "count", "number of", "total", "summarize",
            "are there", "do we have", "does", "is there", "identify", "top", "highest",
            "lowest", "most", "least", "largest", "smallest", "best", "worst", "rank",
        )
        if any(self._contains_phrase(normalized, phrase) for phrase in request_phrases):
            return True
        return bool(filters or conditions or aggregations)

    def _contains_phrase(self, normalized: str, phrase: str) -> bool:
        normalized_phrase = normalize_question(phrase)
        if not normalized_phrase:
            return False
        return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized) is not None

    def _close_phrase(self, normalized: str, normalized_value: str) -> bool:
        if len(normalized_value) < 4:
            return False
        words = normalized.split()
        return any(SequenceMatcher(None, word, normalized_value).ratio() >= 0.88 for word in words)

    def _is_stable_identifier(self, value: str) -> bool:
        return re.fullmatch(r"[A-Z]{0,3}\d{3,4}", value.upper()) is not None

    def _dedupe_resolved_values(self, values: list[ResolvedValue]) -> tuple[ResolvedValue, ...]:
        best_by_field: dict[str, ResolvedValue] = {}
        for value in values:
            existing = best_by_field.get(value.field)
            if existing is None or value.confidence > existing.confidence:
                best_by_field[value.field] = value
        return tuple(best_by_field.values())
