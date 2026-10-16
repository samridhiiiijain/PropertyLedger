from __future__ import annotations

from .schema import load_graph_schema


def uniqueness_constraints() -> tuple[str, ...]:
    schema = load_graph_schema()
    node_constraints = tuple(
        f"CREATE CONSTRAINT {definition['key']}_projection_unique IF NOT EXISTS "
        f"FOR (node:{label}) REQUIRE (node.{definition['key']}, node.projection_version) IS UNIQUE"
        for label, definition in schema.node_labels.items()
    )
    return (
        "CREATE CONSTRAINT graph_projection_name_unique IF NOT EXISTS "
        "FOR (node:GraphProjection) REQUIRE node.name IS UNIQUE",
        "CREATE CONSTRAINT graph_projection_version_unique IF NOT EXISTS "
        "FOR (node:GraphProjectionVersion) REQUIRE node.projection_version IS UNIQUE",
        *node_constraints,
    )


def legacy_constraint_drops() -> tuple[str, ...]:
    schema = load_graph_schema()
    return tuple(
        f"DROP CONSTRAINT {definition['key']}_unique IF EXISTS"
        for definition in schema.node_labels.values()
    )


UNIQUENESS_CONSTRAINTS = uniqueness_constraints()
LEGACY_CONSTRAINT_DROPS = legacy_constraint_drops()


def obsolete_constraint_names(records) -> tuple[str, ...]:
    schema = load_graph_schema()
    key_by_label = {
        label: definition["key"] for label, definition in schema.node_labels.items()
    }
    names: list[str] = []
    for record in records:
        labels = tuple(record["labelsOrTypes"] or ())
        properties = tuple(record["properties"] or ())
        if (
            len(labels) == 1
            and properties == (key_by_label.get(labels[0]),)
            and record["type"] in {"UNIQUENESS", "NODE_KEY"}
        ):
            names.append(str(record["name"]))
    return tuple(names)
