from __future__ import annotations

import re

from .catalog import METRICS, OBJECTS
from .models import QueryPlan, QueryValidationResult


class QueryPlanValidator:
    def validate(self, plan: QueryPlan) -> QueryValidationResult:
        issues: list[str] = []
        query_object = OBJECTS.get(plan.object)

        if query_object is None:
            issues.append(f"Unsupported object: {plan.object}.")
        else:
            allowed_fields = self._allowed_fields(plan.object)
            for field in plan.return_fields:
                if field not in allowed_fields:
                    issues.append(f"Return field is not allowed for {plan.object}: {field}.")

        for item in plan.filters:
            if item.field not in self._allowed_fields(plan.object):
                issues.append(f"Filter field is not allowed for {plan.object}: {item.field}.")
            if item.operator == "in":
                issues.append("The IN filter operator is not supported by the parameterized plan format.")

        for condition in plan.conditions:
            metric = METRICS.get(condition.metric)
            if metric is None:
                issues.append(f"Metric is not approved: {condition.metric}.")
            elif metric.base_object != plan.object:
                issues.append(
                    f"Metric {condition.metric} cannot be applied to object {plan.object}."
                )
            elif metric.kind == "row_filter" and (condition.operator != "=" or condition.value != 1):
                issues.append(f"Row-filter metric {condition.metric} must use equals 1.")
            elif metric.kind == "count" and (
                not isinstance(condition.value, (int, float))
                or isinstance(condition.value, bool)
                or condition.value < 0
            ):
                issues.append(f"Count metric {condition.metric} requires a non-negative numeric threshold.")

        for aggregation in plan.aggregations:
            if aggregation.function == "count" and aggregation.field is not None:
                issues.append("Count aggregations must not specify a field.")
            if aggregation.function == "sum":
                if aggregation.field not in {
                    "invoices.outstanding_amount",
                    "invoices.invoice_amount",
                    "invoices.paid_amount",
                    "payments.amount",
                    "purchase_orders.po_total",
                    "budgets.budget_amount",
                    "budgets.committed_amount",
                }:
                    issues.append(
                        f"Unsupported sum aggregation field: {aggregation.field}."
                    )

        if plan.aggregations and plan.return_fields:
            for field in plan.return_fields:
                if field not in plan.group_by:
                    issues.append("Aggregate plans may only return grouped fields.")
        if plan.aggregations and set(plan.return_fields) != set(plan.group_by):
            issues.append("Aggregate plans must return exactly their grouped fields.")

        if len(plan.return_fields) != len(set(plan.return_fields)):
            issues.append("Return fields must not contain duplicates.")
        if len(plan.group_by) != len(set(plan.group_by)):
            issues.append("Group-by fields must not contain duplicates.")
        aliases = tuple(item.alias for item in plan.aggregations)
        if len(aliases) != len(set(aliases)):
            issues.append("Aggregation aliases must be unique.")

        for field in plan.group_by:
            if field not in self._allowed_group_by_fields(plan.object):
                issues.append(f"Group-by field is not allowed for {plan.object}: {field}.")

        for item in plan.sort:
            if item.field not in self._allowed_fields(plan.object):
                issues.append(f"Sort field is not allowed for {plan.object}: {item.field}.")
            if plan.limit == 1 and item.field not in plan.return_fields and item.field not in plan.group_by:
                issues.append("A single-result ranking must return its sort field for tie checking.")

        for aggregation in plan.aggregations:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", aggregation.alias):
                issues.append(f"Aggregation alias is invalid: {aggregation.alias}.")

        if plan.confidence < 0.85:
            issues.append("Parser confidence is below the deterministic execution threshold.")

        if plan.limit > 100:
            issues.append("Limit cannot exceed 100.")

        if issues:
            return QueryValidationResult(
                is_valid=False,
                message="The query plan cannot be executed safely.",
                issues=tuple(dict.fromkeys(issues)),
            )

        return QueryValidationResult(
            is_valid=True,
            message="The query plan is valid and can be executed.",
        )

    def _allowed_fields(self, object_name: str) -> set[str]:
        query_object = OBJECTS.get(object_name)
        if query_object is None:
            return set()
        fields = set(query_object.allowed_fields)
        if object_name == "invoice":
            fields.update(
                {
                    "properties.property_id",
                    "vendors.vendor_id",
                    "vendors.tax_id",
                }
            )
        return fields

    def _allowed_group_by_fields(self, object_name: str) -> set[str]:
        if object_name == "vendor":
            return {"vendors.vendor_id", "vendors.vendor_name"}
        if object_name == "property":
            return {"properties.property_id", "properties.property_name"}
        if object_name == "invoice":
            return {
                "properties.property_id",
                "properties.property_name",
                "vendors.vendor_id",
                "vendors.vendor_name",
            }
        return set()
