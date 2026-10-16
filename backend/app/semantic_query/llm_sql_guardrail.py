from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from .models import QueryPlan, QueryValidationResult
from .sql_builder import SqlBuildResult


_PLACEHOLDER = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
_COMMENTS = re.compile(r"--|/\*|\*/")
_SYSTEM_TABLE_PREFIXES = ("pg_", "sql_", "sqlite_")
_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Merge,
    exp.Union,
    exp.Intersect,
    exp.Except,
)


@dataclass(frozen=True)
class PreparedSqlCandidate:
    query: SqlBuildResult | None
    validation: QueryValidationResult


class LlmSqlGuardrail:
    """Compile an untrusted SQL proposal against a trusted backend query plan."""

    def prepare(
        self,
        *,
        plan: QueryPlan,
        proposed_sql: str,
        baseline: SqlBuildResult,
    ) -> PreparedSqlCandidate:
        issues: list[str] = []
        if _COMMENTS.search(proposed_sql):
            issues.append("SQL comments are not allowed.")
        if ";" in proposed_sql:
            issues.append("Statement separators are not allowed.")
        if re.search(r"(?:^|\s)(?:pg_catalog|information_schema)\s*\.", proposed_sql, re.I):
            issues.append("System schemas are not allowed.")

        candidate_expression = self._parse_single(proposed_sql, issues)
        baseline_expression = self._parse_single(baseline.sql, issues, label="Backend SQL")
        if candidate_expression is None or baseline_expression is None:
            return self._rejected(issues)

        if not isinstance(candidate_expression, exp.Select):
            issues.append("The proposal must be exactly one SELECT statement.")
        if candidate_expression.args.get("with_") is not None:
            issues.append("CTEs are not allowed in model-generated SQL.")
        if candidate_expression.args.get("limit") is not None:
            issues.append("The model must not provide LIMIT; the backend owns it.")
        if candidate_expression.args.get("offset") is not None:
            issues.append("OFFSET is not allowed in model-generated SQL.")
        if candidate_expression.args.get("locks"):
            issues.append("Row-locking clauses are not allowed.")
        if any(candidate_expression.find(node) is not None for node in _FORBIDDEN_NODES):
            issues.append("Set operations and data-changing SQL are not allowed.")
        if self._has_projection_wildcard(candidate_expression):
            issues.append("SELECT * is not allowed.")

        self._validate_tables(candidate_expression, baseline_expression, issues)
        self._validate_columns(candidate_expression, baseline_expression, issues)
        self._validate_joins(candidate_expression, baseline_expression, issues)
        self._validate_predicates(candidate_expression, baseline_expression, issues)
        self._validate_projection(candidate_expression, baseline_expression, issues)
        self._validate_functions(candidate_expression, baseline_expression, issues)
        self._validate_query_shape(candidate_expression, baseline_expression, issues)
        self._validate_parameters(proposed_sql, baseline.parameters, issues)
        self._validate_literals(candidate_expression, baseline_expression, issues)

        if issues:
            return self._rejected(issues)

        compiled = proposed_sql.strip()
        compiled = f"{compiled}\nLIMIT :limit"
        parameters = dict(baseline.parameters)
        parameters["limit"] = plan.limit
        return PreparedSqlCandidate(
            query=SqlBuildResult(sql=compiled, parameters=parameters),
            validation=QueryValidationResult(
                is_valid=True,
                message="LLM SQL passed AST, intent, placeholder, and join validation.",
            ),
        )

    def _parse_single(
        self,
        sql: str,
        issues: list[str],
        *,
        label: str = "LLM SQL",
    ) -> exp.Expression | None:
        try:
            statements = [item for item in parse(sql, read="postgres") if item is not None]
        except ParseError:
            issues.append(f"{label} could not be parsed.")
            return None
        if len(statements) != 1:
            issues.append(f"{label} must contain exactly one statement.")
            return None
        return statements[0]

    def _validate_tables(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        candidate_tables = self._table_names(candidate)
        baseline_tables = self._table_names(baseline)
        if any(name.startswith(_SYSTEM_TABLE_PREFIXES) for name in candidate_tables):
            issues.append("System tables are not allowed.")
        if candidate_tables != baseline_tables:
            issues.append("The proposal must use exactly the tables required by the validated intent.")

    def _validate_columns(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        if self._column_names(candidate) != self._column_names(baseline):
            issues.append("The proposal must use exactly the columns required by the validated intent.")

    def _validate_joins(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        if self._join_signatures(candidate) != self._join_signatures(baseline):
            issues.append("The proposal contains a missing or unapproved join path.")

    def _validate_predicates(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        if self._placeholder_predicates(candidate) != self._placeholder_predicates(baseline):
            issues.append("Every resolved value must use its contracted field and operator.")
        if self._boolean_shape(candidate) != self._boolean_shape(baseline):
            issues.append("The proposal may not add, remove, or weaken intent predicates.")

    def _validate_projection(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        if not isinstance(candidate, exp.Select) or not isinstance(baseline, exp.Select):
            return
        candidate_names = tuple(item.alias_or_name.lower() for item in candidate.expressions)
        baseline_names = tuple(item.alias_or_name.lower() for item in baseline.expressions)
        if candidate_names != baseline_names:
            issues.append("The proposal must preserve the validated output fields and aliases.")
        candidate_expressions = tuple(
            self._canonical_expression(item) for item in candidate.expressions
        )
        baseline_expressions = tuple(
            self._canonical_expression(item) for item in baseline.expressions
        )
        if candidate_expressions != baseline_expressions:
            issues.append("The proposal must preserve the validated output expressions.")

    def _validate_functions(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        if self._function_names(candidate) != self._function_names(baseline):
            issues.append("The proposal contains a missing or unapproved function.")

    def _validate_query_shape(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        for key, label in (
            ("where", "filter expression"),
            ("group", "grouping"),
            ("having", "aggregate filter"),
            ("order", "ordering"),
        ):
            candidate_clause = candidate.args.get(key)
            baseline_clause = baseline.args.get(key)
            candidate_sql = (
                self._canonical_expression(candidate_clause) if candidate_clause is not None else ""
            )
            baseline_sql = (
                self._canonical_expression(baseline_clause) if baseline_clause is not None else ""
            )
            if candidate_sql != baseline_sql:
                issues.append(f"The proposal must preserve the validated {label}.")
        if bool(candidate.args.get("distinct")) != bool(baseline.args.get("distinct")):
            issues.append("The proposal may not change result distinctness.")

    def _validate_parameters(
        self,
        sql: str,
        baseline_parameters: dict[str, Any],
        issues: list[str],
    ) -> None:
        proposed = _PLACEHOLDER.findall(sql)
        expected = set(baseline_parameters) - {"limit"}
        if set(proposed) != expected or len(proposed) != len(expected):
            issues.append("The proposal must use every backend-resolved placeholder exactly once.")
        if any(name == "limit" for name in proposed):
            issues.append("The model may not provide the result limit.")

    def _validate_literals(
        self,
        candidate: exp.Expression,
        baseline: exp.Expression,
        issues: list[str],
    ) -> None:
        candidate_literals = {node.sql(dialect="postgres") for node in candidate.find_all(exp.Literal)}
        baseline_literals = {node.sql(dialect="postgres") for node in baseline.find_all(exp.Literal)}
        if not candidate_literals.issubset(baseline_literals):
            issues.append("The proposal contains an inline literal not owned by approved business logic.")

    def _table_names(self, expression: exp.Expression) -> frozenset[str]:
        return frozenset(table.name.lower() for table in expression.find_all(exp.Table))

    def _has_projection_wildcard(self, expression: exp.Expression) -> bool:
        return any(
            isinstance(star.parent, (exp.Select, exp.Column))
            for star in expression.find_all(exp.Star)
        )

    def _column_names(self, expression: exp.Expression) -> frozenset[str]:
        aliases = {
            table.alias_or_name.lower(): table.name.lower()
            for table in expression.find_all(exp.Table)
        }
        columns: set[str] = set()
        for column in expression.find_all(exp.Column):
            table = column.table.lower()
            resolved_table = aliases.get(table, table)
            columns.add(f"{resolved_table}.{column.name.lower()}" if resolved_table else column.name.lower())
        return frozenset(columns)

    def _function_names(self, expression: exp.Expression) -> tuple[str, ...]:
        names = []
        for function in expression.find_all(exp.Func):
            names.append(function.sql_name().lower())
        return tuple(sorted(names))

    def _join_signatures(self, expression: exp.Expression) -> tuple[str, ...]:
        signatures: list[str] = []
        for join in expression.find_all(exp.Join):
            table = join.this
            on = join.args.get("on")
            signatures.append(
                "|".join(
                    (
                        str(join.args.get("kind") or "inner").lower(),
                        table.name.lower() if isinstance(table, exp.Table) else table.sql().lower(),
                        self._canonical_expression(on) if on is not None else "",
                    )
                )
            )
        return tuple(signatures)

    def _placeholder_predicates(self, expression: exp.Expression) -> dict[str, str]:
        result: dict[str, str] = {}
        comparison_types = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In)
        for placeholder in expression.find_all(exp.Placeholder):
            parent = placeholder.parent
            while parent is not None and not isinstance(parent, comparison_types):
                parent = parent.parent
            if parent is not None:
                result[str(placeholder.this)] = self._canonical_expression(parent)
        return result

    def _boolean_shape(self, expression: exp.Expression) -> tuple[int, int, int, int]:
        return (
            sum(1 for _ in expression.find_all(exp.Where)),
            sum(1 for _ in expression.find_all(exp.And)),
            sum(1 for _ in expression.find_all(exp.Or)),
            sum(1 for _ in expression.find_all(exp.Subquery)),
        )

    def _canonical_expression(self, expression: exp.Expression) -> str:
        sql = expression.sql(dialect="postgres", normalize=True)
        return re.sub(r"\s+", " ", sql).strip().lower()

    def _rejected(self, issues: list[str]) -> PreparedSqlCandidate:
        return PreparedSqlCandidate(
            query=None,
            validation=QueryValidationResult(
                is_valid=False,
                message="LLM SQL failed local security or intent validation.",
                issues=tuple(dict.fromkeys(issues)),
            ),
        )
