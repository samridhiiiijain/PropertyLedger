from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


# Configuration defaults. Connection details stay deployment-specific; these
# operational limits do not need to be entered in .env for normal deployments.
DEFAULT_NEO4J_QUERY_TIMEOUT_MS = 10000
DEFAULT_NEO4J_MAX_RESULT_COUNT = 100
DEFAULT_NEO4J_PROJECTION_RETAIN_COUNT = 2


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str
    username: str
    password: str
    database: str = "neo4j"
    query_timeout_ms: int = 10000
    max_result_count: int = 100
    projection_retain_count: int = 2


def load_neo4j_settings() -> Neo4jSettings:
    load_local_env()
    uri = os.getenv("NEO4J_URI", "").strip()
    username = os.getenv("NEO4J_USERNAME", "").strip()
    password = os.getenv("NEO4J_PASSWORD", "").strip()
    database = os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
    try:
        query_timeout_ms = int(
            os.getenv("NEO4J_QUERY_TIMEOUT_MS", str(DEFAULT_NEO4J_QUERY_TIMEOUT_MS))
        )
        max_result_count = int(
            os.getenv("NEO4J_MAX_RESULT_COUNT", str(DEFAULT_NEO4J_MAX_RESULT_COUNT))
        )
        projection_retain_count = int(
            os.getenv(
                "NEO4J_PROJECTION_RETAIN_COUNT",
                str(DEFAULT_NEO4J_PROJECTION_RETAIN_COUNT),
            )
        )
    except ValueError as exc:
        raise RuntimeError("Neo4j timeout and result limits must be integers.") from exc
    if query_timeout_ms <= 0 or max_result_count <= 0:
        raise RuntimeError("Neo4j timeout and result limits must be greater than zero.")
    if projection_retain_count < 2:
        raise RuntimeError("NEO4J_PROJECTION_RETAIN_COUNT must be at least 2.")

    missing = [
        name
        for name, value in (
            ("NEO4J_URI", uri),
            ("NEO4J_USERNAME", username),
            ("NEO4J_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Neo4j is not configured. Set these environment variables in .env: "
            + ", ".join(missing)
        )

    return Neo4jSettings(
        uri=uri,
        username=username,
        password=password,
        database=database,
        query_timeout_ms=query_timeout_ms,
        max_result_count=max_result_count,
        projection_retain_count=projection_retain_count,
    )


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(env_path)
