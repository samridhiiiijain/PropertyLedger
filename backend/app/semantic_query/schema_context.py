from __future__ import annotations

from dataclasses import dataclass

from ..semantics.definitions import BUSINESS_DEFINITIONS
from .catalog import METRICS, OBJECTS
from .parser import normalize_question


@dataclass(frozen=True)
class SelectedSchema:
    objects: tuple[str, ...]
    fields: tuple[str, ...]
    metrics: tuple[str, ...]
    metric_definitions: tuple[dict[str, object], ...]
    definitions: tuple[dict[str, object], ...]


class SchemaContextSelector:
    """Build a question-scoped, allowlisted schema context for a planner."""

    def select(self, question: str, preferred_object: str | None = None) -> SelectedSchema:
        normalized = normalize_question(question)
        selected = preferred_object if preferred_object in OBJECTS else None
        if selected is None:
            scores = {
                name: sum(
                    1 for synonym in query_object.synonyms
                    if f" {normalize_question(synonym)} " in f" {normalized} "
                )
                for name, query_object in OBJECTS.items()
            }
            best_name, best_score = max(scores.items(), key=lambda item: item[1])
            selected = best_name if best_score else None

        if selected is None:
            objects = tuple(OBJECTS)
        else:
            objects = (selected,)
            if selected == "invoice":
                objects = ("invoice",)

        fields = tuple(dict.fromkeys(
            field for name in objects for field in OBJECTS[name].allowed_fields
        ))
        relevant_metrics = tuple(
            metric.name
            for metric in METRICS.values()
            if selected is None or metric.base_object == selected
        )
        metric_to_definition = {
            "unpaid_invoice_count": "unpaid-invoice",
            "unpaid_invoice": "unpaid-invoice",
            "vendor_unpaid_invoice_count": "unpaid-invoice",
            "po_variance_invoice": "po-variance",
            "cost_code_over_budget": "cost-code-over-budget",
        }
        relevant_slugs = {
            metric_to_definition[name]
            for name in relevant_metrics
            if name in metric_to_definition
        }
        definitions = tuple(
            {
                "slug": definition.slug,
                "term": definition.term,
                "definition": definition.definition,
                "calculation": definition.calculation,
                "applies_when": definition.applies_when,
                "fields": definition.fields,
                "synonyms": definition.synonyms,
            }
            for definition in BUSINESS_DEFINITIONS
            if definition.slug in relevant_slugs
        )
        metric_definitions = tuple(
            {
                "name": metric.name,
                "synonyms": metric.synonyms,
                "base_object": metric.base_object,
                "kind": metric.kind,
            }
            for metric in METRICS.values()
            if metric.name in relevant_metrics
        )
        return SelectedSchema(
            objects=objects,
            fields=fields,
            metrics=relevant_metrics,
            metric_definitions=metric_definitions,
            definitions=definitions,
        )
