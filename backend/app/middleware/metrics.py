"""Prometheus metrics collection middleware.

Collects HTTP request latency histograms and counters,
plus application-level custom metrics for LLM/ASR/agent operations.
"""

import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry

# Use a dedicated registry so we don't accidentally expose Python runtime
# metrics that may contain sensitive paths.
NOTERO_REGISTRY = CollectorRegistry()

# ── HTTP metrics ──
_http_requests_total = Counter(
    "notero_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=NOTERO_REGISTRY,
)
_http_request_duration_seconds = Histogram(
    "notero_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    registry=NOTERO_REGISTRY,
)

# ── Business metrics ──
_llm_calls_total = Counter(
    "notero_llm_calls_total",
    "Total LLM API calls",
    ["model", "status"],
    registry=NOTERO_REGISTRY,
)
_llm_call_duration_seconds = Histogram(
    "notero_llm_call_duration_seconds",
    "LLM API call latency",
    ["model"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
    registry=NOTERO_REGISTRY,
)

_asr_processing_seconds = Histogram(
    "notero_asr_processing_seconds",
    "ASR audio processing latency",
    ["source"],  # funasr | dashscope
    buckets=[1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
    registry=NOTERO_REGISTRY,
)

_agent_tasks_total = Counter(
    "notero_agent_tasks_total",
    "Total agent tasks",
    ["role", "status"],
    registry=NOTERO_REGISTRY,
)

_vector_index_rebuilds_total = Counter(
    "notero_vector_index_rebuilds_total",
    "Total vector index rebuilds",
    ["scope", "status"],  # session | notebook
    registry=NOTERO_REGISTRY,
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request latency and count per method/path/status."""

    async def dispatch(self, request: Request, call_next):
        # Skip metrics endpoint to avoid recursive self-measurement noise
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        # Normalize path: replace UUIDs and IDs with placeholders to avoid cardinality explosion
        path = _normalize_path(request.url.path)

        status = str(response.status_code)
        _http_requests_total.labels(method=request.method, path=path, status_code=status).inc()
        _http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
        return response


def _normalize_path(path: str) -> str:
    """Replace dynamic segments with placeholders to keep label cardinality low."""
    import re
    # Replace UUIDs
    path = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "{id}", path)
    # Replace numeric IDs (simple heuristic)
    path = re.sub(r"/\d+", "/{id}", path)
    return path


# ── Helpers for business metrics ──

def observe_llm_call(model: str, duration_seconds: float, success: bool = True):
    status = "success" if success else "error"
    _llm_calls_total.labels(model=model, status=status).inc()
    _llm_call_duration_seconds.labels(model=model).observe(duration_seconds)


def observe_asr_processing(source: str, duration_seconds: float):
    _asr_processing_seconds.labels(source=source).observe(duration_seconds)


def observe_agent_task(role: str, success: bool = True):
    status = "success" if success else "error"
    _agent_tasks_total.labels(role=role, status=status).inc()


def observe_vector_rebuild(scope: str, success: bool = True):
    status = "success" if success else "error"
    _vector_index_rebuilds_total.labels(scope=scope, status=status).inc()


def metrics_response() -> tuple[bytes, str]:
    """Generate Prometheus exposition format response."""
    return generate_latest(NOTERO_REGISTRY), CONTENT_TYPE_LATEST
