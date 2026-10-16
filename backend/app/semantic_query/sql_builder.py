from __future__ import annotations

from typing import Any

from .catalog import (
    FIELD_DEPENDENCIES,
    FIELD_EXPRESSIONS,
    FIELD_RESULT_ALIASES,
    JOIN_SPECS,
    METRICS,
    OBJECTS,
    TABLE_ALIASES,
)
from .models import QueryPlan


class SqlBuildResult:
    def __init__(self, sql: str, parameters: dict[str, Any]) -> None:
        self.sql = sql
        self.parameters = parameters


class SemanticSqlBuilder:
    def build(self, plan: QueryPlan) -> SqlBuildResult:
        query_object = OBJECTS[plan.object]
        select_clause = self._select_clause(plan, query_object.alias)
        where_clauses: list[str] = []
        parameters: dict[str, Any] = {}
        joins = self._joins_for_plan(plan)

        for index, item in enumerate(plan.filters, start=1):
            parameter_name = f"filter_{index}"
            where_clauses.append(
                f"{self._field_sql(item.field, query_object.alias)} {item.operator} :{parameter_name}"
            )
            parameters[parameter_name] = item.value

        for index, condition in enumerate(plan.conditions, start=1):
            metric = METRICS[condition.metric]
            parameter_name = f"condition_{index}"
            if metric.kind == "count":
                where_clauses.append(
                    "("
                    f"SELECT COUNT(*) FROM {metric.related_table} {metric.related_alias} "
                    f"WHERE {metric.join_condition} AND {metric.condition_sql}"
                    f") {condition.operator} :{parameter_name}"
                )
                parameters[parameter_name] = condition.value
            elif metric.kind == "row_filter":
                where_clauses.append(metric.condition_sql)

        where_sql = f"\nWHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        group_sql = ""
        if plan.group_by:
            group_parts = tuple(self._field_sql(field, query_object.alias) for field in plan.group_by)
            group_sql = f"\nGROUP BY {', '.join(group_parts)}"
        order_sql = ""
        if plan.sort:
            order_parts = tuple(
                f"{self._field_sql(item.field, query_object.alias)} {item.direction.upper()}"
                for item in plan.sort
            )
            order_sql = f"\nORDER BY {', '.join(order_parts)}"

        parameters["limit"] = plan.limit
        sql = (
            f"SELECT\n  {select_clause}\n"
            f"FROM {query_object.table} {query_object.alias}"
            f"{joins}"
            f"{where_sql}"
            f"{group_sql}"
            f"{order_sql}\n"
            "LIMIT :limit"
        )
        return SqlBuildResult(sql=sql, parameters=parameters)

    def _select_clause(self, plan: QueryPlan, base_alias: str) -> str:
        if plan.aggregations:
            grouped_fields = tuple(
                f"{self._field_sql(field, base_alias)} AS {self._column_alias(field, plan.object)}"
                for field in plan.group_by
            )
            aggregate_fields = tuple(
                f"{self._aggregation_sql(aggregation)} AS {aggregation.alias}"
                for aggregation in plan.aggregations
            )
            return ",\n  ".join((*grouped_fields, *aggregate_fields))

        return ",\n  ".join(
            f"{self._field_sql(field, base_alias)} AS {self._column_alias(field, plan.object)}"
            for field in plan.return_fields
        )

    def _aggregation_sql(self, aggregation) -> str:
        if aggregation.function == "count":
            return "COUNT(*)"
        if aggregation.function == "sum" and aggregation.field:
            expression = self._field_sql(aggregation.field, TABLE_ALIASES.get(aggregation.field.split(".", 1)[0], "i"))
            return f"COALESCE(SUM({expression}), 0)"
        raise ValueError(f"Unsupported aggregation: {aggregation}")

    def _joins_for_plan(self, plan: QueryPlan) -> str:
        query_object = OBJECTS[plan.object]
        required_tables: set[str] = set()
        fields = [
            *(item.field for item in plan.filters),
            *plan.return_fields,
            *plan.group_by,
            *(item.field for item in plan.sort),
            *(item.field for item in plan.aggregations if item.field),
        ]
        for field in fields:
            table = field.split(".", 1)[0]
            required_tables.add(table)
            required_tables.update(FIELD_DEPENDENCIES.get(field, ()))
        for condition in plan.conditions:
            metric = METRICS[condition.metric]
            required_tables.update(metric.required_tables)

        join_specs = JOIN_SPECS.get(plan.object, {})
        join_tables = required_tables - {query_object.table}
        unsupported_tables = join_tables - set(join_specs)
        if unsupported_tables:
            raise ValueError("The plan requires a table with no approved relationship.")
        return "".join(
            f"\n{join_specs[table]}"
            for table in join_specs
            if table in join_tables
        )

    def _field_sql(self, field: str, base_alias: str) -> str:
        table, column = field.split(".", 1)
        return FIELD_EXPRESSIONS.get(
            field,
            f"{TABLE_ALIASES.get(table, base_alias)}.{column}",
        )

    def _column_alias(self, field: str, object_name: str) -> str:
        if object_name == "property":
            return field.split(".", 1)[1]
        if object_name == "vendor":
            return field.split(".", 1)[1]
        return FIELD_RESULT_ALIASES.get(field, field.split(".", 1)[1])
