from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .config import Neo4jSettings, load_neo4j_settings
from .constraints import (
    LEGACY_CONSTRAINT_DROPS,
    UNIQUENESS_CONSTRAINTS,
    obsolete_constraint_names,
)
from .schema import GraphSchema, load_graph_schema, validate_graph_path
from .queries import (
    ACTIVATE_EXISTING_PROJECTION_QUERY,
    ACTIVATE_PROJECTION_QUERY,
    CREATE_PROJECTION_VERSION_QUERY,
    DELETE_LEGACY_GRAPH_QUERY,
    DELETE_PROJECTION_VERSION_QUERY,
    LIST_PROJECTION_VERSIONS_QUERY,
    PROJECTION_COUNTS_QUERY,
    TRACE_PO_VARIANCE_PATHS_QUERY,
    UPSERT_DOCUMENT_LINKS_QUERY,
    UPSERT_DOCUMENTS_QUERY,
    UPSERT_GRAPH_QUERY,
)


PROJECTION_NAME = "finance"


class GraphUnavailableError(RuntimeError):
    pass


class GraphProjectionMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphProjectionBuildResult:
    projection_version: str
    counts: dict[str, int]
    removed_versions: tuple[str, ...] = ()


class Neo4jGraphRepository:
    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self.settings = settings or load_neo4j_settings()
        self.schema: GraphSchema = load_graph_schema()
        if not self.schema.read_only or not self.schema.keys_only:
            raise RuntimeError("The graph schema must enforce read-only key-based queries.")
        self._driver: Any | None = None

    @property
    def driver(self) -> Any:
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise GraphUnavailableError(
                    "The neo4j Python driver is not installed. Run pip install -r backend/requirements.txt."
                ) from exc
            self._driver = GraphDatabase.driver(
                self.settings.uri,
                auth=(self.settings.username, self.settings.password),
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def verify_connection(self) -> None:
        try:
            self.driver.verify_connectivity()
        except Exception as exc:
            raise GraphUnavailableError(f"Neo4j connection failed: {exc}") from exc

    def ensure_constraints(self) -> None:
        with self.driver.session(database=self.settings.database) as session:
            for statement in LEGACY_CONSTRAINT_DROPS:
                session.run(statement).consume()
            records = session.run(
                "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties "
                "RETURN name, type, labelsOrTypes, properties"
            )
            for name in obsolete_constraint_names(records):
                escaped_name = name.replace("`", "``")
                session.run(f"DROP CONSTRAINT `{escaped_name}` IF EXISTS").consume()
            for statement in UNIQUENESS_CONSTRAINTS:
                session.run(statement).consume()

    def replace_projection(
        self,
        *,
        projection_version: str,
        source_fingerprint: str,
        invoices: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        document_links: list[dict[str, Any]],
        expected_counts: dict[str, int],
    ) -> GraphProjectionBuildResult:
        def build_and_activate(transaction: Any) -> dict[str, int]:
            common = {
                "projection_name": PROJECTION_NAME,
                "projection_version": projection_version,
            }
            transaction.run(
                CREATE_PROJECTION_VERSION_QUERY,
                **common,
                source_fingerprint=source_fingerprint,
                expected_counts=json.dumps(expected_counts, sort_keys=True),
            ).consume()
            transaction.run(
                UPSERT_GRAPH_QUERY,
                projection_version=projection_version,
                invoices=invoices,
            ).consume()
            transaction.run(
                UPSERT_DOCUMENTS_QUERY,
                projection_version=projection_version,
                documents=documents,
            ).consume()
            transaction.run(
                UPSERT_DOCUMENT_LINKS_QUERY,
                projection_version=projection_version,
                links=document_links,
            ).consume()
            record = transaction.run(
                PROJECTION_COUNTS_QUERY,
                projection_version=projection_version,
            ).single(strict=True)
            actual_counts = {key: int(record[key]) for key in expected_counts}
            if actual_counts != expected_counts:
                raise GraphProjectionMismatch(
                    f"Graph projection count mismatch: expected {expected_counts}, got {actual_counts}."
                )
            activated = transaction.run(
                ACTIVATE_PROJECTION_QUERY,
                **common,
                actual_counts=json.dumps(actual_counts, sort_keys=True),
            ).single(strict=True)
            if activated["active_version"] != projection_version:
                raise GraphProjectionMismatch("Neo4j did not activate the rebuilt projection.")
            return actual_counts

        with self.driver.session(database=self.settings.database) as session:
            counts = session.execute_write(build_and_activate)
            session.run(
                DELETE_LEGACY_GRAPH_QUERY,
                managed_labels=list(self.schema.node_labels),
            ).consume()
        removed = self.cleanup_old_versions(self.settings.projection_retain_count)
        return GraphProjectionBuildResult(
            projection_version=projection_version,
            counts=counts,
            removed_versions=removed,
        )

    def activate_projection(self, projection_version: str) -> None:
        with self.driver.session(database=self.settings.database) as session:
            record = session.run(
                ACTIVATE_EXISTING_PROJECTION_QUERY,
                projection_name=PROJECTION_NAME,
                projection_version=projection_version,
            ).single()
            if record is None:
                raise GraphProjectionMismatch(
                    "Only a complete projection version can be activated."
                )

    def list_projection_versions(self) -> tuple[dict[str, Any], ...]:
        with self.driver.session(database=self.settings.database) as session:
            result = session.run(
                LIST_PROJECTION_VERSIONS_QUERY,
                projection_name=PROJECTION_NAME,
            )
            return tuple(dict(record) for record in result)

    def cleanup_old_versions(self, retain_count: int) -> tuple[str, ...]:
        versions = self.list_projection_versions()
        keep = {
            item["projection_version"] for item in versions if item.get("active")
        }
        for item in versions:
            if len(keep) >= retain_count:
                break
            keep.add(item["projection_version"])
        removable = tuple(
            item["projection_version"]
            for item in versions
            if item["projection_version"] not in keep
        )
        if not removable:
            return ()
        with self.driver.session(database=self.settings.database) as session:
            for version in removable:
                session.run(
                    DELETE_PROJECTION_VERSION_QUERY,
                    projection_version=version,
                ).consume()
        return removable

    def active_projection_version(self) -> str | None:
        versions = self.list_projection_versions()
        return next(
            (item["projection_version"] for item in versions if item.get("active")),
            None,
        )

    def projection_counts(self, projection_version: str) -> dict[str, int]:
        keys = (
            "properties",
            "projects",
            "vendors",
            "purchase_orders",
            "cost_codes",
            "invoices",
            "documents",
            "document_links",
        )
        with self.driver.session(database=self.settings.database) as session:
            record = session.run(
                PROJECTION_COUNTS_QUERY,
                projection_version=projection_version,
            ).single(strict=True)
            return {key: int(record[key]) for key in keys}

    def trace_po_variance_paths(self, property_id: str) -> list[dict[str, Any]]:
        with self.driver.session(database=self.settings.database) as session:
            result = session.run(
                TRACE_PO_VARIANCE_PATHS_QUERY,
                projection_name=PROJECTION_NAME,
                property_id=property_id,
                result_limit=self.settings.max_result_count,
                timeout=self.settings.query_timeout_ms / 1000,
            )
            paths = [record["path"] for record in result]
            for path in paths:
                validate_graph_path(path, self.schema)
            return paths
