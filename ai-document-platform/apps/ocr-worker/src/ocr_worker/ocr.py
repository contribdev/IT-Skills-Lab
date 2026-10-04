"""OCR pipeline: PDF → text using pdf2image + Tesseract.

All CPU-bound work runs in a thread pool (via asyncio.to_thread) so the
event loop stays free to handle RabbitMQ heartbeats and metrics.
"""

import asyncio
from io import BytesIO

import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image

from ocr_worker.config import get_settings
from ocr_worker.logging import get_logger

log = get_logger(__name__)


class OCRError(Exception):
    """Base class for OCR-related errors."""


class PDFInvalidError(OCRError):
    """PDF cannot be parsed (bad format, corrupted, empty)."""


class OCRTooManyPagesError(OCRError):
    """PDF has more pages than the configured maximum."""


class OCRTimeoutError(OCRError):
    """OCR exceeded the configured timeout."""


def _extract_single_page(image: Image.Image, lang: str) -> str:
    """Run Tesseract on one page image. Synchronous — call via to_thread."""
    return pytesseract.image_to_string(image, lang=lang)


async def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Convert PDF bytes to plain text.

    Returns:
        (text, page_count) — extracted text and number of pages processed.

    Raises:
        PDFInvalidError: if the PDF cannot be parsed.
        OCRTooManyPagesError: if the PDF exceeds ocr_max_pages.
        OCRTimeoutError: if processing exceeds ocr_timeout_seconds.
    """
    settings = get_settings()

    if not pdf_bytes:
        raise PDFInvalidError("empty PDF")

    # --- Convert PDF → images (CPU-bound, run in thread) ---
    try:
        images = await asyncio.to_thread(
            convert_from_bytes,
            pdf_bytes,
            dpi=settings.ocr_dpi,
            fmt="png",
        )
    except Exception as exc:
        log.warning("pdf_conversion_failed", error=str(exc))
        raise PDFInvalidError(f"pdf2image failed: {exc}") from exc

    if not images:
        raise PDFInvalidError("PDF contains no pages")

    if len(images) > settings.ocr_max_pages:
        raise OCRTooManyPagesError(
            f"PDF has {len(images)} pages, max is {settings.ocr_max_pages}"
        )

    log.info(
        "pdf_converted",
        pages=len(images),
        dpi=settings.ocr_dpi,
        languages=settings.ocr_languages,
    )

    # --- OCR each page (CPU-bound, run in thread, with timeout) ---
    try:
        ocr_coro = _ocr_pages(images, settings.ocr_languages)
        text = await asyncio.wait_for(ocr_coro, timeout=settings.ocr_timeout_seconds)
    except asyncio.TimeoutError as exc:
        log.warning("ocr_timeout", pages=len(images), timeout=settings.ocr_timeout_seconds)
        raise OCRTimeoutError(
            f"OCR exceeded {settings.ocr_timeout_seconds}s for {len(images)} pages"
        ) from exc

    return text, len(images)


async def _ocr_pages(images: list[Image.Image], lang: str) -> str:
    """OCR all pages in a thread pool, sequentially per page.

    Parallel per-page OCR would oversubscribe CPU; sequential is faster in
    practice for small documents and simpler for the thread pool.
    """
    parts: list[str] = []
    for idx, image in enumerate(images, start=1):
        page_text = await asyncio.to_thread(_extract_single_page, image, lang)
        parts.append(page_text)
        log.debug("page_ocr_done", page=idx, chars=len(page_text))

    return "\n\n".join(parts)