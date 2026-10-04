"""Prometheus metrics for the OCR Worker.

The worker is not an HTTP server, so there are no auto-instrumented
metrics. Instead, we expose counters, histograms and gauges that the
worker's main loop updates directly.
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

OCR_PROCESSED_TOTAL = Counter(
    "ocr_processed_total",
    "Total number of OCR tasks processed",
    labelnames=("status",),  # success | failed
)

OCR_ERRORS_TOTAL = Counter(
    "ocr_errors_total",
    "Total number of OCR errors by type",
    labelnames=("type",),  # s3_download | pdf_invalid | ocr_timeout | db_error | publish_error | unknown
)

OCR_PAGES_TOTAL = Counter(
    "ocr_pages_total",
    "Total number of PDF pages processed",
)

# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

OCR_DURATION_SECONDS = Histogram(
    "ocr_duration_seconds",
    "Time to process a single document (seconds)",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

# ---------------------------------------------------------------------------
# Gauge
# ---------------------------------------------------------------------------

OCR_ACTIVE_JOBS = Gauge(
    "ocr_active_jobs",
    "Number of OCR tasks currently being processed",
)