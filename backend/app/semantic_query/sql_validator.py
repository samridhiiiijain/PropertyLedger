from __future__ import annotations

import re

from .models import QueryPlan, QueryValidationResult


FORBIDDEN_SQL_TOKENS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "attach",
    "detach",
    "pragma",
    "vacuum",
)


class SqlSafetyValidator:
    """Validate generated SQL before execution.

    This is a second guardrail after plan validation. It is intentionally
    conservative and only accepts the SQL shape emitted by SemanticSqlBuilder.
    """

    def validate(
        self,
        *,
        plan: QueryPlan,
        sql: str,
        parameters: dict[str, object],
    ) -> QueryValidationResult:
        issues: list[str] = []
        normalized = self._normalize_sql(sql)

        if not normalized.startswith("select "):
            issues.append("Generated SQL must be read-only SELECT.")

        if ";" in sql:
            issues.append("Generated SQL must not contain statement separators.")

        if "--" in sql or "/*" in sql or "*/" in sql:
            issues.append("Generated SQL must not contain comments.")

        token_pattern = re.compile(r"\b(" + "|".join(FORBIDDEN_SQL_TOKENS) + r")\b", re.IGNORECASE)
        if token_pattern.search(sql):
            issues.append("Generated SQL contains a forbidden SQL operation.")

        if " limit :limit" not in normalized:
            issues.append("Generated SQL must include a parameterized LIMIT.")

        if "limit" not in parameters:
            issues.append("Generated SQL parameters must include limit.")

        placeholders = set(re.findall(r":([a-zA-Z_][a-zA-Z0-9_]*)", sql))
        parameter_names = set(parameters)
        if placeholders != parameter_names:
            issues.append("Generated SQL placeholders must exactly match provided parameters.")

        issues.extend(self._table_issues(plan, normalized))
        issues.extend(self._parameterization_issues(sql, parameters))

        if issues:
            return QueryValidationResult(
                is_valid=False,
                message="Generated SQL failed the safety guardrail.",
                issues=tuple(dict.fromkeys(issues)),
            )

        return QueryValidationResult(
            is_valid=True,
            message="Generated SQL passed the safety guardrail.",
        )

    def _table_issues(self, plan: QueryPlan, normalized: str) -> list[str]:
        issues: list[str] = []
        if plan.object == "property":
            if " from properties p" not in normalized:
                issues.append("Property queries must read from properties p.")
            if " join " in normalized:
                issues.append("Property queries may not add joins in this phase.")

        if plan.object == "invoice":
            if " from invoices i" not in normalized:
                issues.append("Invoice queries must read from invoices i.")
            needs_property_join = any(item.field.startswith("properties.") for item in plan.filters) or any(
                field.startswith("properties.") for field in plan.return_fields
            )
            needs_vendor_join = any(item.field.startswith("vendors.") for item in plan.filters) or any(
                field.startswith("vendors.") for field in plan.group_by
            ) or any(
                field.startswith("vendors.") for field in plan.return_fields
            )
            needs_po_join = (
                any(condition.metric == "po_variance_invoice" for condition in plan.conditions)
                or any(field.startswith("purchase_orders.") for field in plan.return_fields)
                or "invoices.po_variance_amount" in plan.return_fields
            )
            needs_budget_join = any(
                field.startswith("budgets.") for field in plan.return_fields
            )
            has_property_join = " join properties p on p.property_id = i.property_id" in normalized
            has_vendor_join = " join vendors v on v.vendor_id = i.vendor_id" in normalized
            has_po_join = " join purchase_orders po on po.po_id = i.po_id" in normalized
            has_budget_join = (
                " left join budgets b on b.property_id = i.property_id "
                "and b.project_id = i.project_id and b.cost_code = i.cost_code"
            ) in normalized
            if needs_property_join and not has_property_join:
                issues.append("Invoice queries with property filters must use the approved property join.")
            if not needs_property_join and " join properties p" in normalized:
                issues.append("Invoice queries must not join properties unless a property filter requires it.")
            if needs_vendor_join and not has_vendor_join:
                issues.append("Invoice queries with vendor filters must use the approved vendor join.")
            if not needs_vendor_join and " join vendors v" in normalized:
                issues.append("Invoice queries must not join vendors unless a vendor filter requires it.")
            if needs_po_join and not has_po_join:
                issues.append("Invoice PO variance queries must use the approved purchase-order join.")
            if not needs_po_join and " join purchase_orders po" in normalized:
                issues.append("Invoice queries must not join purchase orders unless PO variance requires it.")
            if needs_budget_join and not has_budget_join:
                issues.append("Invoice budget fields must use the approved budget join.")
            if not needs_budget_join and " join budgets b" in normalized:
                issues.append("Invoice queries must not join budgets unless budget fields require it.")

        if plan.object == "vendor":
            if " from vendors v" not in normalized:
                issues.append("Vendor queries must read from vendors v.")
            if " join " in normalized:
                issues.append("Vendor queries may not add joins in this phase.")

        if plan.object == "budget":
            if " from budgets b" not in normalized:
                issues.append("Budget queries must read from budgets b.")
            if " join " in normalized:
                issues.append("Budget queries may not add joins in this phase.")

        return issues

    def _parameterization_issues(
        self,
        sql: str,
        parameters: dict[str, object],
    ) -> list[str]:
        issues: list[str] = []
        for key, value in parameters.items():
            if key == "limit":
                continue
            if isinstance(value, str) and f"'{value}'" in sql:
                issues.append("Generated SQL must not inline string parameter values.")
        return issues

    def _normalize_sql(self, sql: str) -> str:
        return re.sub(r"\s+", " ", sql.strip()).lower()
