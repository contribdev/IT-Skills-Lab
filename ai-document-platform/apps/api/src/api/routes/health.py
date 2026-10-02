"""Health and readiness endpoints.

- /healthz: liveness probe. Always returns 200 if the process is alive.
- /readyz:  readiness probe. Checks dependencies (DB, S3, RabbitMQ).
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from api.db import check_db
from api.logging import get_logger
from api.rabbit import check_rabbitmq
from api.s3 import check_s3

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    """Liveness probe. Returns 200 unconditionally."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness probe. Checks DB, S3 and RabbitMQ.

    Returns 200 only if all dependencies are reachable; otherwise 503
    with per-dependency status so operators can see which dependency
    is failing.
    """
    db_ok = await check_db()
    s3_ok = await check_s3()
    rabbit_ok = await check_rabbitmq()

    dependencies = {
        "database": db_ok,
        "s3": s3_ok,
        "rabbitmq": rabbit_ok,
    }

    all_ok = all(dependencies.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    if not all_ok:
        log.warning("readiness_failed", **dependencies)
    else:
        log.debug("readiness_ok")

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if all_ok else "degraded",
            "dependencies": dependencies,
        },
    )