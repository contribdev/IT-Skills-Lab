"""Pydantic schemas for the public API contract.

Schemas separate the internal ORM representation (models.py) from the
external JSON representation. They validate requests and responses, and
drive OpenAPI documentation.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatusEnum(str, enum.Enum):
    """Public status values exposed via the API."""

    UPLOADED = "uploaded"
    OCR_PROCESSING = "ocr_processing"
    OCR_DONE = "ocr_done"
    LLM_PROCESSING = "llm_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentResponse(BaseModel):
    """Short document representation for lists and status queries."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique document identifier")
    original_filename: str = Field(..., description="Original file name")
    status: DocumentStatusEnum = Field(..., description="Current processing status")
    created_at: datetime = Field(..., description="Creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC)")


class DocumentResultResponse(BaseModel):
    """Full document result including the structured payload from the LLM."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique document identifier")
    status: DocumentStatusEnum = Field(..., description="Current processing status")
    result: dict[str, Any] | None = Field(
        None,
        description="Structured result from the LLM (null until completed)",
    )
    error_message: str | None = Field(
        None,
        description="Error message if processing failed",
    )


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse] = Field(..., description="Documents on this page")
    total: int = Field(..., ge=0, description="Total number of documents matching filters")
    limit: int = Field(..., ge=1, description="Page size")
    offset: int = Field(..., ge=0, description="Offset from the start of the result set")


class ErrorResponse(BaseModel):
    """Unified error response body."""

    detail: str = Field(..., description="Human-readable error message")
    code: str = Field(..., description="Machine-readable error code")