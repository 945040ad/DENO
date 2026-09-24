"""Metrics (Prometheus) and error reporting (Sentry), shared by API and worker.

Everything is optional: without SENTRY_DSN nothing is sent, and metrics are just in-process counters
until something scrapes them.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import Counter, Histogram

from deno_core.logging import get_logger
from deno_core.settings import Settings

log = get_logger(__name__)

HTTP_REQUESTS = Counter("deno_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "deno_http_request_seconds", "HTTP request latency", ["method", "route"], buckets=(0.01, 0.05, 0.1, 0.3, 1, 3, 10)
)
RUNS = Counter("deno_runs_total", "Validation runs by final status", ["status"])
RUN_SECONDS = Histogram("deno_run_seconds", "Validation run duration", buckets=(30, 60, 120, 180, 240, 360, 600, 1200))
NODE_SECONDS = Histogram(
    "deno_graph_node_seconds", "Graph node duration", ["graph", "node"], buckets=(0.5, 2, 5, 15, 30, 60, 120, 300)
)
SOURCE_POSTS = Counter("deno_source_posts_total", "Posts collected per source", ["source"])
SOURCE_ERRORS = Counter("deno_source_errors_total", "Source collection errors", ["source", "kind"])
LLM_TOKENS = Counter("deno_llm_tokens_total", "LLM tokens used", ["model", "direction"])
LLM_COST = Counter("deno_llm_cost_usd_total", "LLM cost in USD")
GATE_RESULTS = Counter("deno_gate_results_total", "Draft gate outcomes", ["outcome"])


def init_sentry(settings: Settings, component: Literal["api", "worker"]) -> None:
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,  # no emails, IPs or request bodies
        server_name=f"deno-{component}",
    )
    log.info("sentry_enabled", component=component)
