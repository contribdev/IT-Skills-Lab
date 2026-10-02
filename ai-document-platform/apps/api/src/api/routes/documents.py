"""Document endpoints: upload, status, result, list."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db import get_db
from api.logging import get_logger
from api.models import Document, DocumentStatus
from api.rabbit import publish_ocr_task
from api.routes.metrics import DOCUMENTS_UPLOADED
from api.s3 import upload_bytes
from api.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentResultResponse,
    DocumentStatusEnum,
    ErrorResponse,
)

log = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# POST /documents — upload a PDF
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file type"},
        413: {"model": ErrorResponse, "description": "File too large"},
    },
)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF document to process")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentResponse:
    """Upload a PDF document for processing.

    The document is stored in S3, a row is created in the database with
    status=uploaded, and a task is published to the OCR queue. Processing
    happens asynchronously; poll GET /documents/{id} for status.
    """
    settings = get_settings()

    # ----- Validate content type -----
    if file.content_type != "application/pdf":
        DOCUMENTS_UPLOADED.labels(outcome="rejected").inc()
        log.warning("upload_rejected", reason="invalid_content_type", content_type=file.content_type)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Only application/pdf is accepted", "code": "invalid_content_type"},
        )

    # ----- Read file into memory (with size check) -----
    max_size = settings.max_upload_size_mb * 1024 * 1024
    data = await file.read()
    if len(data) > max_size:
        DOCUMENTS_UPLOADED.labels(outcome="rejected").inc()
        log.warning("upload_rejected", reason="too_large", size_bytes=len(data), max_bytes=max_size)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "detail": f"File too large; max {settings.max_upload_size_mb} MB",
                "code": "file_too_large",
            },
        )

    if len(data) == 0:
        DOCUMENTS_UPLOADED.labels(outcome="rejected").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Empty file", "code": "empty_file"},
        )

    # ----- Upload to S3 first (no DB row if S3 fails) -----
    document_id = uuid.uuid4()
    s3_key = f"originals/{document_id}.pdf"
    try:
        await upload_bytes(s3_key, data, content_type="application/pdf")
    except Exception as exc:
        DOCUMENTS_UPLOADED.labels(outcome="failed").inc()
        log.error("s3_upload_failed", document_id=str(document_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "Storage unavailable", "code": "storage_error"},
        ) from exc

    # ----- Create DB row -----
    doc = Document(
        id=document_id,
        original_filename=file.filename or "document.pdf",
        status=DocumentStatus.UPLOADED,
        s3_original_key=s3_key,
    )
    db.add(doc)
    try:
        await db.commit()
        await db.refresh(doc)
    except Exception as exc:
        log.error("db_insert_failed", document_id=str(document_id), error=str(exc))
        DOCUMENTS_UPLOADED.labels(outcome="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "Database error", "code": "db_error"},
        ) from exc

    # ----- Publish to OCR queue -----
    try:
        await publish_ocr_task(str(document_id))
    except Exception as exc:
        # DB row exists, but no task. Mark as failed so it's visible.
        log.error("publish_failed", document_id=str(document_id), error=str(exc))
        doc.status = DocumentStatus.FAILED
        doc.error_message = f"Failed to enqueue OCR task: {exc}"
        await db.commit()
        DOCUMENTS_UPLOADED.labels(outcome="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "Queue unavailable", "code": "queue_error"},
        ) from exc

    DOCUMENTS_UPLOADED.labels(outcome="accepted").inc()
    log.info(
        "document_accepted",
        document_id=str(document_id),
        filename=doc.original_filename,
        size_bytes=len(data),
    )
    return DocumentResponse.model_validate(doc)

@router.get(
    "",
    response_model=DocumentListResponse,
)
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[
        DocumentStatusEnum | None,
        Query(alias="status", description="Filter by status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size")] = 20,
    offset: Annotated[int, Query(ge=0, description="Offset from start")] = 0,
) -> DocumentListResponse:
    """List documents with optional status filter and pagination.

    Results are ordered by created_at descending (newest first).
    """
    # Base query
    base = select(Document)

    if status_filter is not None:
        base = base.where(Document.status == DocumentStatus(status_filter.value))

    # Count total matching
    count_query = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Fetch page
    page_query = base.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(page_query)
    docs = result.scalars().all()

    log.info(
        "documents_listed",
        total=total,
        returned=len(docs),
        limit=limit,
        offset=offset,
        status=status_filter.value if status_filter else None,
    )

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total,
        limit=limit,
        offset=offset,
    )

@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentResponse:
    """Get the current status of a document by its ID."""
    doc = await db.get(Document, document_id)

    if doc is None:
        log.info("document_not_found", document_id=str(document_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Document not found", "code": "not_found"},
        )

    return DocumentResponse.model_validate(doc)

@router.get(
    "/{document_id}/result",
    response_model=DocumentResultResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
        409: {"model": ErrorResponse, "description": "Document is not ready"},
    },
)
async def get_document_result(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DocumentResultResponse:
    """Get the structured LLM result of a document.

    Returns 409 if the document is still processing or has failed.
    """
    doc = await db.get(Document, document_id)

    if doc is None:
        log.info("document_not_found", document_id=str(document_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Document not found", "code": "not_found"},
        )

    if doc.status == DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": doc.error_message or "Document processing failed",
                "code": "processing_failed",
            },
        )

    if doc.status != DocumentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": f"Document is not ready; current status: {doc.status.value}",
                "code": "not_ready",
            },
        )

    return DocumentResultResponse(
        id=doc.id,
        status=doc.status,
        result=doc.result_json,
        error_message=doc.error_message,
    )