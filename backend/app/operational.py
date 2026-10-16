from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Any


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
LATENCY_BUCKETS_MS = (25, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000)


@dataclass
class _Metric:
    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0
    max_duration_ms: float = 0
    in_flight: int = 0
    max_in_flight: int = 0
    latency_buckets: list[int] | None = None

    def __post_init__(self) -> None:
        self.latency_buckets = [0] * (len(LATENCY_BUCKETS_MS) + 1)


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._metrics: dict[str, _Metric] = defaultdict(_Metric)

    def begin(self, path: str) -> None:
        with self._lock:
            metric = self._metrics[path]
            metric.in_flight += 1
            metric.max_in_flight = max(metric.max_in_flight, metric.in_flight)

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            metric = self._metrics[path]
            metric.count += 1
            metric.errors += int(status_code >= 500)
            metric.total_duration_ms += duration_ms
            metric.max_duration_ms = max(metric.max_duration_ms, duration_ms)
            metric.in_flight = max(0, metric.in_flight - 1)
            bucket_index = next(
                (
                    index
                    for index, upper_bound in enumerate(LATENCY_BUCKETS_MS)
                    if duration_ms <= upper_bound
                ),
                len(LATENCY_BUCKETS_MS),
            )
            metric.latency_buckets[bucket_index] += 1

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                path: {
                    "requests": metric.count,
                    "errors": metric.errors,
                    "average_duration_ms": round(
                        metric.total_duration_ms / metric.count, 2
                    ),
                    "p95_duration_ms": self._percentile(metric, 0.95),
                    "max_duration_ms": round(metric.max_duration_ms, 2),
                    "in_flight": metric.in_flight,
                    "max_in_flight": metric.max_in_flight,
                }
                for path, metric in sorted(self._metrics.items())
                if metric.count
            }

    def _percentile(self, metric: _Metric, percentile: float) -> float:
        target = max(1, int(metric.count * percentile + 0.999999))
        cumulative = 0
        for index, count in enumerate(metric.latency_buckets or ()):
            cumulative += count
            if cumulative >= target:
                if index < len(LATENCY_BUCKETS_MS):
                    return float(LATENCY_BUCKETS_MS[index])
                return round(metric.max_duration_ms, 2)
        return round(metric.max_duration_ms, 2)


class TextToSqlMetrics:
    def __init__(
        self,
        *,
        input_cost_per_million_usd: float = 0,
        output_cost_per_million_usd: float = 0,
    ) -> None:
        self._lock = Lock()
        self._events: dict[str, int] = defaultdict(int)
        self._prompt_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._models: dict[str, int] = defaultdict(int)
        self._input_rate = input_cost_per_million_usd
        self._output_rate = output_cost_per_million_usd

    def record_event(self, event: str) -> None:
        with self._lock:
            self._events[event] += 1

    def record_usage(
        self,
        model: str,
        prompt_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> None:
        with self._lock:
            self._models[model] += 1
            self._prompt_tokens += max(0, prompt_tokens)
            self._output_tokens += max(0, output_tokens)
            self._total_tokens += max(0, total_tokens)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            estimated_cost = (
                self._prompt_tokens * self._input_rate
                + self._output_tokens * self._output_rate
            ) / 1_000_000
            return {
                "events": dict(sorted(self._events.items())),
                "usage": {
                    "prompt_tokens": self._prompt_tokens,
                    "output_tokens": self._output_tokens,
                    "total_tokens": self._total_tokens,
                    "requests_by_model": dict(sorted(self._models.items())),
                    "estimated_cost_usd": round(estimated_cost, 6),
                    "cost_rates_configured": bool(
                        self._input_rate or self._output_rate
                    ),
                },
            }


def readiness_payload(
    *,
    structured_store: Any,
    document_repository: Any,
    graph_repository_factory: Any,
) -> tuple[dict[str, object], bool]:
    components: dict[str, object] = {
        "structured_store": structured_store.readiness(),
        "document_index": document_repository.readiness(),
    }
    graph_repository = None
    try:
        graph_repository = graph_repository_factory()
        graph_repository.verify_connection()
        active_version = graph_repository.active_projection_version()
        components["neo4j"] = (
            {"status": "ready", "projection_version": active_version}
            if active_version
            else {"status": "unavailable", "error_type": "MissingActiveProjection"}
        )
    except Exception as exc:
        components["neo4j"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
        }
    finally:
        if graph_repository is not None:
            graph_repository.close()

    ready = all(
        isinstance(component, dict) and component.get("status") == "ready"
        for component in components.values()
    )
    return {
        "status": "ready" if ready else "not_ready",
        "components": components,
    }, ready
