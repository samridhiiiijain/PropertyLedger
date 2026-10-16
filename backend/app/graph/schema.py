from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "graph_schema.json"


@dataclass(frozen=True)
class GraphSchema:
    node_labels: dict[str, dict[str, Any]]
    relationships: tuple[dict[str, str], ...]
    read_only: bool
    keys_only: bool

    @property
    def relationship_types(self) -> frozenset[str]:
        return frozenset(item["type"] for item in self.relationships)


def load_graph_schema(path: Path = SCHEMA_PATH) -> GraphSchema:
    payload = json.loads(path.read_text(encoding="utf-8"))
    node_labels = payload.get("node_labels", {})
    relationships = tuple(payload.get("relationships", ()))
    if not node_labels or not relationships:
        raise RuntimeError("The graph schema must declare node labels and relationships.")
    for label, definition in node_labels.items():
        if not definition.get("key") or definition["key"] not in definition.get("properties", []):
            raise RuntimeError(f"Graph label {label} must declare its key property.")
    for relationship in relationships:
        if relationship.get("from") not in node_labels or relationship.get("to") not in node_labels:
            raise RuntimeError(f"Graph relationship has an undeclared endpoint: {relationship}")
        if not relationship.get("type"):
            raise RuntimeError("Every graph relationship must declare a type.")
    policy = payload.get("query_policy", {})
    return GraphSchema(
        node_labels=node_labels,
        relationships=relationships,
        read_only=bool(policy.get("read_only")),
        keys_only=policy.get("allowed_node_properties") == "keys_only",
    )


def validate_graph_path(path: dict[str, Any], schema: GraphSchema) -> None:
    labels = {node["label"] for node in path.get("path_nodes", ())}
    edge_types = {edge["type"] for edge in path.get("path_edges", ())}
    if not labels.issubset(schema.node_labels):
        raise RuntimeError("Neo4j returned a node label outside the declared graph schema.")
    if not edge_types.issubset(schema.relationship_types):
        raise RuntimeError("Neo4j returned a relationship outside the declared graph schema.")
