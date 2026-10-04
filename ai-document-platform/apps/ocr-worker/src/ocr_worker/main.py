"""OCR Worker entrypoint.

Consumes tasks from ocr.queue, runs Tesseract, stores text in S3 and
updates the database. Exposes Prometheus metrics on :9090/metrics.
"""

import asyncio
import signal
import time
from typing import Any

from prometheus_client import start_http_server

from ocr_worker.config import get_settings
from ocr_worker.db import dispose_engine, get_session_maker
from ocr_worker.logging import configure_logging, get_logger
from ocr_worker.metrics import (
    OCR_ACTIVE_JOBS,
    OCR_DURATION_SECONDS,
    OCR_ERRORS_TOTAL,
    OCR_PAGES_TOTAL,
    OCR_PROCESSED_TOTAL,
)
from ocr_worker.models import Document, DocumentStatus
from ocr_worker.ocr import (
    OCRError,
    OCRTimeoutError,
    OCRTooManyPagesError,
    PDFInvalidError,
    extract_text_from_pdf,
)
from ocr_worker.rabbit import close_rabbitmq, consume_ocr_queue, publish_llm_task
from ocr_worker.s3 import close_s3_session, download_bytes, upload_bytes

log = get_logger(__name__)

_shutdown = asyncio.Event()


# ---------------------------------------------------------------------------
# Error → metric label mapping
# ---------------------------------------------------------------------------

def _classify_error(exc: Exception) -> str:
    """Map an exception to a low-cardinality metric label."""
    if isinstance(exc, PDFInvalidError):
        return "pdf_invalid"
    if isinstance(exc, OCRTooManyPagesError):
        return "pdf_too_many_pages"
    if isinstance(exc, OCRTimeoutError):
        return "ocr_timeout"
    if isinstance(exc, OCRError):
        return "ocr_error"
    return "unknown"


# ---------------------------------------------------------------------------
# Per-document handler
# ---------------------------------------------------------------------------

async def handle_document(document_id: str) -> None:
    """Process a single document: DB → S3 → OCR → S3 → DB → queue."""
    start = time.perf_counter()
    OCR_ACTIVE_JOBS.inc()

    try:
        # --- Load document from DB ---
        async with get_session_maker()() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                log.warning("document_not_found", document_id=document_id)
                OCR_ERRORS_TOTAL.labels(type="document_not_found").inc()
                OCR_PROCESSED_TOTAL.labels(status="failed").inc()
                return

            if doc.status == DocumentStatus.OCR_DONE:
                log.info("document_already_ocr_done", document_id=document_id)
                OCR_PROCESSED_TOTAL.labels(status="skipped").inc()
                return

            # Mark as processing
            doc.status = DocumentStatus.OCR_PROCESSING
            await session.commit()
            original_key = doc.s3_original_key

        # --- Download PDF from S3 ---
        try:
            pdf_bytes = await download_bytes(original_key)
        except Exception as exc:
            log.error("s3_download_failed", document_id=document_id, error=str(exc))
            OCR_ERRORS_TOTAL.labels(type="s3_download").inc()
            await _mark_failed(document_id, f"S3 download failed: {exc}")
            OCR_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        # --- OCR ---
        try:
            text, pages = await extract_text_from_pdf(pdf_bytes)
        except OCRError as exc:
            log.error(
                "ocr_failed",
                document_id=document_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            OCR_ERRORS_TOTAL.labels(type=_classify_error(exc)).inc()
            await _mark_failed(document_id, f"OCR failed: {exc}")
            OCR_PROCESSED_TOTAL.labels(status="failed").inc()
            return
        except Exception as exc:
            log.exception("ocr_unexpected_error", document_id=document_id)
            OCR_ERRORS_TOTAL.labels(type="unknown").inc()
            await _mark_failed(document_id, f"Unexpected OCR error: {exc}")
            OCR_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        OCR_PAGES_TOTAL.inc(pages)

        # --- Upload text to S3 ---
        extracted_key = f"extracted/{document_id}.txt"
        try:
            await upload_bytes(
                extracted_key,
                text.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )
        except Exception as exc:
            log.error("s3_upload_failed", document_id=document_id, error=str(exc))
            OCR_ERRORS_TOTAL.labels(type="s3_upload").inc()
            await _mark_failed(document_id, f"S3 upload failed: {exc}")
            OCR_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        # --- Update DB: ocr_done ---
        async with get_session_maker()() as session:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.OCR_DONE
                doc.s3_extracted_key = extracted_key
                await session.commit()

        # --- Publish to llm.queue ---
        try:
            await publish_llm_task(document_id)
        except Exception as exc:
            log.error("publish_llm_failed", document_id=document_id, error=str(exc))
            OCR_ERRORS_TOTAL.labels(type="publish").inc()
            await _mark_failed(document_id, f"Publish to llm.queue failed: {exc}")
            OCR_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        OCR_PROCESSED_TOTAL.labels(status="success").inc()
        log.info(
            "document_ocr_done",
            document_id=document_id,
            pages=pages,
            chars=len(text),
        )
    finally:
        OCR_ACTIVE_JOBS.dec()
        OCR_DURATION_SECONDS.observe(time.perf_counter() - start)


async def _mark_failed(document_id: str, error_message: str) -> None:
    """Set the document status to failed with an error message."""
    try:
        async with get_session_maker()() as session:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_message[:1000]  # truncate
                await session.commit()
    except Exception as exc:
        log.error("mark_failed_errored", document_id=document_id, error=str(exc))


# ---------------------------------------------------------------------------
# Signal handling & main
# ---------------------------------------------------------------------------

def _handle_signal(sig: int, _frame: Any) -> None:
    log.info("signal_received", signal=signal.Signals(sig).name)
    _shutdown.set()


async def main() -> None:
    configure_logging()
    settings = get_settings()

    log.info(
        "worker_starting",
        service="ocr-worker",
        queue=settings.ocr_queue,
        llm_queue=settings.llm_queue,
        prefetch=settings.prefetch_count,
        ocr_languages=settings.ocr_languages,
        ocr_dpi=settings.ocr_dpi,
    )

    # Start Prometheus metrics server
    start_http_server(9090)
    log.info("metrics_server_started", port=9090)

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig, None)

    # Consume until shutdown
    try:
        consumer_task = asyncio.create_task(consume_ocr_queue(handle_document))
        await _shutdown.wait()
        log.info("shutdown_requested")
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    finally:
        log.info("worker_stopping")
        await close_rabbitmq()
        await dispose_engine()
        await close_s3_session()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())