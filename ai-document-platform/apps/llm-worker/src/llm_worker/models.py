"""SQLAlchemy ORM models for the API service.
Duplicated from apps/api/src/api/models.py — keep in sync.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from llm_worker.db import Base


class DocumentStatus(str, enum.Enum):
    """Lifecycle states of a document."""

    UPLOADED = "uploaded"
    OCR_PROCESSING = "ocr_processing"
    OCR_DONE = "ocr_done"
    LLM_PROCESSING = "llm_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """A document submitted for processing."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=expression.text("gen_random_uuid()"),
    )

    original_filename: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(
            DocumentStatus,
            name="document_status",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=expression.text("'uploaded'"),
    )

    s3_original_key: Mapped[str] = mapped_column(Text, nullable=False)
    s3_extracted_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_result_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_documents_status", "status"),
        Index("idx_documents_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} status={self.status.value} file={self.original_filename!r}>"