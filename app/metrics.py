from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


REQUEST_TOTAL = Counter(
    "payment_api_requests_total",
    "Total number of HTTP requests served by payment-api",
    ["method", "path", "status", "mode"],
)

REQUEST_FAILED = Counter(
    "payment_api_failed_requests_total",
    "Total number of failed requests served by payment-api",
    ["endpoint", "error_type", "mode"],
)

PAYMENT_LATENCY = Histogram(
    "payment_api_payment_latency_seconds",
    "Latency distribution for /pay transactions",
    ["endpoint", "outcome", "mode"],
    buckets=(0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.8, 1, 1.5, 2, 3, 5),
)

PAYMENT_OUTCOMES = Counter(
    "payment_api_payment_outcomes_total",
    "Count of simulated payment outcomes by mode",
    ["outcome", "mode"],
)

DB_POOL_EXHAUSTED = Counter(
    "payment_api_db_pool_exhausted_total",
    "Count of simulated database pool exhausted events",
    ["mode"],
)

TIMEOUT_COUNT = Counter(
    "payment_api_timeout_total",
    "Count of simulated timeout events",
    ["mode"],
)

INCIDENT_THRESHOLD_BREACH = Counter(
    "payment_api_incident_threshold_breach_total",
    "Count of threshold breaches observed by incident detection logic",
    ["signal"],
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
