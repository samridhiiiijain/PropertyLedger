from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import QueryPlan, QueryValidationResult


class QueryResultValidator:
    def validate(
        self,
        plan: QueryPlan,
        rows: tuple[dict[str, Any], ...],
    ) -> QueryValidationResult:
        expected_fields: set[str] = set()
        if plan.aggregations:
            expected_fields.update(self._field_alias(field, plan.object) for field in plan.group_by)
            expected_fields.update(item.alias for item in plan.aggregations)
        else:
            expected_fields.update(self._field_alias(field, plan.object) for field in plan.return_fields)

        issues: list[str] = []
        if len(rows) > plan.limit:
            issues.append("The database returned more rows than the approved query limit.")
        for row in rows:
            if set(row) != expected_fields:
                issues.append("The database result shape does not match the validated plan.")
                break
            if any(
                not isinstance(value, (str, int, float, Decimal, date, datetime, bytes, type(None)))
                for value in row.values()
            ):
                issues.append("The database returned an unsupported result value.")
                break
            if any(isinstance(value, float) and (value != value or abs(value) == float("inf")) for value in row.values()):
                issues.append("The database returned a non-finite numeric value.")
                break

        if issues:
            return QueryValidationResult(
                is_valid=False,
                message="Database result validation failed.",
                issues=tuple(dict.fromkeys(issues)),
            )
        return QueryValidationResult(is_valid=True, message="Database results passed validation.")

    def _field_alias(self, field: str, object_name: str) -> str:
        if object_name in {"property", "vendor"}:
            return field.split(".", 1)[1]
        return {
            "properties.property_name": "property_name",
            "properties.city": "property_city",
            "properties.property_type": "property_type",
            "properties.status": "property_status",
            "vendors.vendor_name": "vendor_name",
            "vendors.category": "vendor_category",
            "vendors.city": "vendor_city",
            "vendors.tax_id": "vendor_tax_id",
        }.get(field, field.split(".", 1)[1])
