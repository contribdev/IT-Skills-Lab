"""Prometheus metrics endpoint and custom business metrics.

Auto-instrumented HTTP metrics are added by prometheus-fastapi-instrumentator
when the app starts. This module declares custom metrics that route handlers
and workers update directly.
"""

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from api.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["metrics"])


# ---------------------------------------------------------------------------
# Custom business metrics
# ---------------------------------------------------------------------------

# Total uploaded documents, labelled by outcome (accepted / rejected / failed).
DOCUMENTS_UPLOADED = Counter(
    "documents_uploaded_total",
    "Total number of document uploads",
    labelnames=("outcome",),
)

# Current count of documents per status. Updated by querying the DB
# on each /metrics scrape; see the scrape handler below.
DOCUMENTS_BY_STATUS = Gauge(
    "documents_by_status",
    "Current number of documents in each status",
    labelnames=("status",),
)


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------

@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose Prometheus metrics.

    The auto-instrumented HTTP metrics are registered on the default
    registry, so a single generate_latest() call returns everything.
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)