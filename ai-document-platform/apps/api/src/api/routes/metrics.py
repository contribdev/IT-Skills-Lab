"""Prometheus metrics endpoint and custom business metrics.

Auto-instrumented HTTP metrics are added by prometheus-fastapi-instrumentator
when the app starts. This module declares custom metrics that route handlers
and workers update directly.
"""

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from sqlalchemy import func, select

from api.db import get_session_maker
from api.logging import get_logger
from api.models import Document, DocumentStatus

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

async def _update_documents_by_status() -> None:
    """Query DB and update the documents_by_status gauge."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        query = select(Document.status, func.count()).group_by(Document.status)
        result = await session.execute(query)
        counts_by_status = {row[0]: row[1] for row in result.all()}

    # Reset all labels to 0, then set actual counts
    for status in DocumentStatus:
        DOCUMENTS_BY_STATUS.labels(status=status.value).set(
            counts_by_status.get(status, 0)
        )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose Prometheus metrics.

    The auto-instrumented HTTP metrics are registered on the default
    registry, so a single generate_latest() call returns everything.
    """
    try:
        await _update_documents_by_status()
    except Exception as exc:
        log.warning("failed_to_update_documents_by_status", error=str(exc))

    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)