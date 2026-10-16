from __future__ import annotations

import sqlite3
from typing import Any

from .models import QueryValidationResult


class ReadOnlySqliteExecutor:
    """Execute one statement with SQLite's authorizer denying all writes."""

    _ALLOWED_ACTIONS = frozenset(
        action
        for action in (
            getattr(sqlite3, "SQLITE_SELECT", None),
            getattr(sqlite3, "SQLITE_READ", None),
            getattr(sqlite3, "SQLITE_FUNCTION", None),
            getattr(sqlite3, "SQLITE_RECURSIVE", None),
        )
        if action is not None
    )

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def fetch_all(self, sql: str, parameters: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        if hasattr(self.connection, "set_authorizer"):
            import sqlite3

            def authorize(action: int, _arg1: str | None, _arg2: str | None, _db: str | None, _source: str | None) -> int:
                return sqlite3.SQLITE_OK if action in self._ALLOWED_ACTIONS else sqlite3.SQLITE_DENY

            self.connection.set_authorizer(authorize)
            try:
                cursor = self.connection.execute(sql, parameters)
                return tuple(dict(row) for row in cursor.fetchall())
            finally:
                self.connection.set_authorizer(None)

        cursor = self.connection.execute(sql, parameters)
        return tuple(dict(row) for row in cursor.fetchall())

    def validate_cost(
        self,
        sql: str,
        parameters: dict[str, Any],
        *,
        max_cost: int,
        max_rows: int,
    ) -> QueryValidationResult:
        if hasattr(self.connection, "explain"):
            cost, rows = self.connection.explain(sql, parameters)
            issues = []
            if cost > max_cost:
                issues.append("The estimated query cost exceeds the configured maximum.")
            if rows > max_rows:
                issues.append("The estimated result size exceeds the configured maximum.")
            return QueryValidationResult(
                is_valid=not issues,
                message=(
                    "The query plan is within configured cost limits."
                    if not issues
                    else "The query plan exceeds configured cost limits."
                ),
                issues=tuple(issues),
            )

        # SQLite is the local-development fallback and has no comparable cost estimate.
        self.connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameters).fetchall()
        return QueryValidationResult(
            is_valid=True,
            message="The local query compiled; PostgreSQL enforces production cost estimates.",
        )
