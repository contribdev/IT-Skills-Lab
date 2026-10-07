"""LLM Worker entrypoint.

Consumes tasks from llm.queue, calls Ollama, validates the JSON output,
stores it in S3 and updates the database. Exposes Prometheus metrics on
:9091/metrics.
"""

import asyncio
import signal
import time
from typing import Any

from prometheus_client import start_http_server
from pydantic import ValidationError

from llm_worker.config import get_settings
from llm_worker.db import dispose_engine, get_session_maker
from llm_worker.logging import configure_logging, get_logger
from llm_worker.metrics import (
    LLM_ACTIVE_JOBS,
    LLM_DURATION_SECONDS,
    LLM_ERRORS_TOTAL,
    LLM_PROCESSED_TOTAL,
)
from llm_worker.models import Document, DocumentStatus
from llm_worker.ollama import (
    OllamaError,
    OllamaHTTPError,
    OllamaInvalidJSONError,
    OllamaTimeoutError,
    check_ollama,
    generate_json,
)
from llm_worker.prompts import SYSTEM_PROMPT, build_user_prompt
from llm_worker.rabbit import close_rabbitmq, consume_llm_queue
from llm_worker.s3 import close_s3_session, download_bytes, upload_bytes
from llm_worker.schemas import ExtractedDocument

log = get_logger(__name__)

_shutdown = asyncio.Event()


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def _classify_ollama_error(exc: Exception) -> str:
    """Map an Ollama exception to a low-cardinality metric label."""
    if isinstance(exc, OllamaTimeoutError):
        return "ollama_timeout"
    if isinstance(exc, OllamaInvalidJSONError):
        return "invalid_json"
    if isinstance(exc, OllamaHTTPError):
        return "ollama_error"
    if isinstance(exc, OllamaError):
        return "ollama_error"
    return "unknown"


# ---------------------------------------------------------------------------
# Per-document handler
# ---------------------------------------------------------------------------

async def handle_document(document_id: str) -> None:
    """Process a single document: DB → S3 → Ollama → S3 → DB."""
    start = time.perf_counter()
    LLM_ACTIVE_JOBS.inc()

    try:
        # --- Load document from DB ---
        async with get_session_maker()() as session:
            doc = await session.get(Document, document_id)
            if doc is None:
                log.warning("document_not_found", document_id=document_id)
                LLM_ERRORS_TOTAL.labels(type="document_not_found").inc()
                LLM_PROCESSED_TOTAL.labels(status="failed").inc()
                return

            if doc.status == DocumentStatus.COMPLETED:
                log.info("document_already_completed", document_id=document_id)
                LLM_PROCESSED_TOTAL.labels(status="skipped").inc()
                return

            if not doc.s3_extracted_key:
                log.warning("document_no_extracted_key", document_id=document_id)
                LLM_ERRORS_TOTAL.labels(type="no_extracted_key").inc()
                await _mark_failed(document_id, "No extracted text available")
                LLM_PROCESSED_TOTAL.labels(status="failed").inc()
                return

            doc.status = DocumentStatus.LLM_PROCESSING
            await session.commit()
            extracted_key = doc.s3_extracted_key

        # --- Download extracted text from S3 ---
        try:
            raw_bytes = await download_bytes(extracted_key)
        except Exception as exc:
            log.error("s3_download_failed", document_id=document_id, error=str(exc))
            LLM_ERRORS_TOTAL.labels(type="s3_download").inc()
            await _mark_failed(document_id, f"S3 download failed: {exc}")
            LLM_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        text = raw_bytes.decode("utf-8", errors="replace")

        # --- Truncate very long texts ---
        settings = get_settings()
        if len(text) > settings.max_text_chars:
            log.info(
                "text_truncated",
                document_id=document_id,
                original_chars=len(text),
                max_chars=settings.max_text_chars,
            )
            text = text[: settings.max_text_chars]

        # --- Call Ollama ---
        user_prompt = build_user_prompt(text)
        try:
            ollama_result = await generate_json(user_prompt, system_prompt=SYSTEM_PROMPT)
        except OllamaError as exc:
            log.error(
                "ollama_failed",
                document_id=document_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            LLM_ERRORS_TOTAL.labels(type=_classify_ollama_error(exc)).inc()
            await _mark_failed(document_id, f"Ollama failed: {exc}")
            LLM_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        # --- Validate with Pydantic ---
        try:
            extracted = ExtractedDocument.model_validate(ollama_result.data)
        except ValidationError as exc:
            log.error(
                "schema_validation_failed",
                document_id=document_id,
                error=str(exc)[:300],
            )
            LLM_ERRORS_TOTAL.labels(type="invalid_schema").inc()
            await _mark_failed(document_id, f"Schema validation failed: {exc}")
            LLM_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        # --- Serialize for storage ---
        result_dict = extracted.model_dump(mode="json")
        result_json_bytes = extracted.model_dump_json().encode("utf-8")
        result_key = f"results/{document_id}.json"

        # --- Upload to S3 ---
        try:
            await upload_bytes(
                result_key,
                result_json_bytes,
                content_type="application/json",
            )
        except Exception as exc:
            log.error("s3_upload_failed", document_id=document_id, error=str(exc))
            LLM_ERRORS_TOTAL.labels(type="s3_upload").inc()
            await _mark_failed(document_id, f"S3 upload failed: {exc}")
            LLM_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        # --- Update DB ---
        try:
            async with get_session_maker()() as session:
                doc = await session.get(Document, document_id)
                if doc is not None:
                    doc.status = DocumentStatus.COMPLETED
                    doc.result_json = result_dict
                    doc.s3_result_key = result_key
                    await session.commit()
        except Exception as exc:
            log.error("db_update_failed", document_id=document_id, error=str(exc))
            LLM_ERRORS_TOTAL.labels(type="db_error").inc()
            await _mark_failed(document_id, f"DB update failed: {exc}")
            LLM_PROCESSED_TOTAL.labels(status="failed").inc()
            return

        LLM_PROCESSED_TOTAL.labels(status="success").inc()
        log.info(
            "document_completed",
            document_id=document_id,
            document_type=extracted.document_type.value,
            confidence=extracted.confidence,
            result_chars=len(result_json_bytes),
            prompt_tokens=ollama_result.usage.prompt_tokens,
            completion_tokens=ollama_result.usage.completion_tokens,
        )
    finally:
        LLM_ACTIVE_JOBS.dec()
        LLM_DURATION_SECONDS.observe(time.perf_counter() - start)


async def _mark_failed(document_id: str, error_message: str) -> None:
    """Set the document status to failed with an error message."""
    try:
        async with get_session_maker()() as session:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_message[:1000]
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
        service="llm-worker",
        queue=settings.llm_queue,
        prefetch=settings.prefetch_count,
        ollama_endpoint=settings.ollama_endpoint,
        ollama_model=settings.ollama_model,
    )

    # --- Ollama health check before starting ---
    if not await check_ollama():
        log.error("ollama_unreachable_at_startup", endpoint=settings.ollama_endpoint)
        raise SystemExit(1)

    log.info("ollama_ready", endpoint=settings.ollama_endpoint, model=settings.ollama_model)

    # --- Start Prometheus metrics server ---
    start_http_server(settings.metrics_port)
    log.info("metrics_server_started", port=settings.metrics_port)

    # --- Register signal handlers ---
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig, None)

    # --- Consume until shutdown ---
    try:
        consumer_task = asyncio.create_task(consume_llm_queue(handle_document))
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