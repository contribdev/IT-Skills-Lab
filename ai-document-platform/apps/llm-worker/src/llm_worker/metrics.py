"""Prometheus metrics for the LLM Worker.

The worker is not an HTTP server. Metrics are exposed on :9090/metrics
by main.py via prometheus_client.start_http_server().
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

LLM_PROCESSED_TOTAL = Counter(
    "llm_processed_total",
    "Total number of LLM tasks processed",
    labelnames=("status",),  # success | failed | skipped
)

LLM_ERRORS_TOTAL = Counter(
    "llm_errors_total",
    "Total number of LLM errors by type",
    labelnames=("type",),
    # Possible values:
    #   s3_download | s3_upload | ollama_timeout | ollama_error
    #   invalid_json | invalid_schema | db_error | unknown
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total number of tokens consumed or produced",
    labelnames=("kind",),  # prompt | completion
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

LLM_DURATION_SECONDS = Histogram(
    "llm_duration_seconds",
    "Total time to process a single document (S3 + Ollama + DB)",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 180, 300),
)

LLM_OLLAMA_REQUEST_SECONDS = Histogram(
    "llm_ollama_request_seconds",
    "Time spent waiting for the Ollama API",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 180),
)

# ---------------------------------------------------------------------------
# Gauge
# ---------------------------------------------------------------------------

LLM_ACTIVE_JOBS = Gauge(
    "llm_active_jobs",
    "Number of LLM tasks currently being processed",
)