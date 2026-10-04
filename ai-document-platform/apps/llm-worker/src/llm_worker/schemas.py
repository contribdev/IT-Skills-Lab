"""Pydantic schemas for validating the LLM output.

The ExtractedDocument model is the contract between the LLM Worker
and downstream consumers (API, DB). If the LLM returns a payload that
does not conform, we reject it and mark the document as failed.
"""

import enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(str, enum.Enum):
    INVOICE = "invoice"
    CONTRACT = "contract"
    ACT = "act"
    RECEIPT = "receipt"
    OTHER = "other"


class PartyRole(str, enum.Enum):
    SELLER = "seller"
    BUYER = "buyer"
    CONTRACTOR = "contractor"
    CUSTOMER = "customer"
    OTHER = "other"


class AmountRole(str, enum.Enum):
    TOTAL = "total"
    VAT = "vat"
    SUBTOTAL = "subtotal"
    OTHER = "other"


class DateType(str, enum.Enum):
    ISSUE = "issue"
    DUE = "due"
    SIGNING = "signing"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Nested models
# ---------------------------------------------------------------------------

class Party(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: PartyRole = PartyRole.OTHER
    name: str | None = None
    inn: str | None = None
    kpp: str | None = None


class Amount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: AmountRole = AmountRole.OTHER
    value: float
    currency: str = "RUB"


class DateItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: DateType = DateType.OTHER
    value: str  # YYYY-MM-DD


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class ExtractedDocument(BaseModel):
    """Structured output extracted from a document by the LLM."""

    model_config = ConfigDict(extra="ignore")

    document_type: DocumentType = DocumentType.OTHER
    summary: str = ""
    parties: list[Party] = Field(default_factory=list)
    amounts: list[Amount] = Field(default_factory=list)
    dates: list[DateItem] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    language: str = "ru"