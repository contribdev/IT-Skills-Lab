"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from api.db import dispose_engine
from api.logging import configure_logging
from api.rabbit import close_rabbitmq
from api.routes.documents import router as documents_router
from api.routes.health import router as health_router
from api.routes.metrics import router as metrics_router
from api.s3 import close_s3_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: configure logging on startup, close resources on shutdown."""
    configure_logging()
    yield
    await dispose_engine()
    await close_rabbitmq()
    await close_s3_session()


app = FastAPI(
    title="AI Document Intelligence Platform — API",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Prometheus instrumentation
# ---------------------------------------------------------------------------
# Adds automatic HTTP metrics:
#   - http_requests_total{method, handler, status}
#   - http_request_duration_seconds{method, handler, le}
#   - http_requests_inprogress{method, handler}
# Exposes them on the /metrics endpoint (which our metrics router also serves;
# the instrumentator is configured to only instrument, not to expose).
Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
).instrument(app)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(documents_router)