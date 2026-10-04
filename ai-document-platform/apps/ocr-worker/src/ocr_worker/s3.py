"""Async S3 layer using aioboto3.

Wraps the MinIO bucket used for storing original PDFs, extracted text,
and LLM results. All operations are async and share a single client
per process.

Duplicated from apps/api/src/api/s3.py — keep in sync.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import aioboto3
from botocore.exceptions import ClientError

from ocr_worker.config import get_settings
from ocr_worker.logging import get_logger
log = get_logger(__name__)

_session: aioboto3.Session | None = None


def _get_session() -> aioboto3.Session:
    """Return the process-wide aioboto3 session (lazy singleton)."""
    global _session
    if _session is None:
        _session = aioboto3.Session()
        log.info("s3_session_created")
    return _session


@asynccontextmanager
async def get_s3_client() -> AsyncIterator[Any]:
    """Yield an async S3 client. Caller must use it as async context manager.

    Usage:
        async with get_s3_client() as s3:
            await s3.put_object(...)
    """
    settings = get_settings()
    session = _get_session()
    async with session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
    ) as client:
        yield client


async def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    """Upload raw bytes to the documents bucket."""
    settings = get_settings()
    async with get_s3_client() as s3:
        await s3.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    log.info("s3_uploaded", key=key, size_bytes=len(data), content_type=content_type)


async def download_bytes(key: str) -> bytes:
    """Download an object as bytes."""
    settings = get_settings()
    async with get_s3_client() as s3:
        response = await s3.get_object(Bucket=settings.s3_bucket, Key=key)
        async with response["Body"] as stream:
            data = await stream.read()
    log.info("s3_downloaded", key=key, size_bytes=len(data))
    return data


async def delete_object(key: str) -> None:
    """Delete an object. Idempotent — no error if the key doesn't exist."""
    settings = get_settings()
    async with get_s3_client() as s3:
        await s3.delete_object(Bucket=settings.s3_bucket, Key=key)
    log.info("s3_deleted", key=key)


async def object_exists(key: str) -> bool:
    """Return True if the object exists, False otherwise."""
    settings = get_settings()
    try:
        async with get_s3_client() as s3:
            await s3.head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


async def check_s3() -> bool:
    """Health check: verify the bucket is reachable via HEAD."""
    settings = get_settings()
    try:
        async with get_s3_client() as s3:
            await s3.head_bucket(Bucket=settings.s3_bucket)
        return True
    except Exception as exc:
        log.error("s3_health_check_failed", error=str(exc))
        return False


async def close_s3_session() -> None:
    """Drop the cached session. Called on application shutdown."""
    global _session
    _session = None
    log.info("s3_session_closed")