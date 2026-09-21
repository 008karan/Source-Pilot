from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventStage(str, Enum):
    DRAFT = "draft"
    RFX_REVIEW = "rfx_review"
    COLLECTING_RESPONSES = "collecting_responses"
    PROCESSING_RESPONSES = "processing_responses"
    EXCEPTION_REVIEW = "exception_review"
    READY_FOR_ANALYSIS = "ready_for_analysis"


class ExceptionStatus(str, Enum):
    AUTO_VERIFIED = "auto_verified"
    NEEDS_REVIEW = "needs_review"
    BLOCKING = "blocking"
    RESOLVED_BY_BUYER = "resolved_by_buyer"
    CLARIFICATION_REQUIRED = "clarification_required"


class EvidenceRef(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    page_number: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    paragraph_index: int | None = None
    body_span: tuple[int, int] | None = None
    source_text: str | None = None
    preview_uri: str | None = None


class ExtractedFact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    supplier_id: UUID
    response_id: UUID
    document_id: UUID
    fact_type: str
    rfx_line_item_id: UUID | None = None
    raw_label: str | None = None
    raw_value: str | None = None
    parsed_value: str | float | int | bool | None = None
    raw_unit: str | None = None
    raw_currency: str | None = None
    confidence: float = Field(ge=0, le=1)
    extraction_method: str
    evidence_id: UUID
    verification_status: str = "unverified"


class ConversionStep(BaseModel):
    operation: str
    input_value: Any
    output_value: Any
    rule_id: str | None = None
    explanation: str


class TransformationTrace(BaseModel):
    source_fact_ids: list[UUID]
    steps: list[ConversionStep]
    assumptions: list[str] = []


class NormalizedQuoteLine(BaseModel):
    supplier_id: UUID
    rfx_line_item_id: UUID
    quote_status: Literal["quoted", "not_quoted", "unclear"]
    normalized_unit_price: float | None = None
    normalized_uom: str | None = None
    normalized_currency: str | None = None
    landed_unit_cost: float | None = None
    total_extended_cost: float | None = None
    qualification_status: Literal["pass", "fail", "pending"] = "pending"
    confidence: float = Field(default=1, ge=0, le=1)
    blocking_exception: bool = False
    trace: TransformationTrace | None = None


class ScenarioSpec(BaseModel):
    objective: Literal["minimize_landed_cost"] = "minimize_landed_cost"
    qualified_suppliers_only: bool = True
    max_supplier_spend_share: float | None = Field(default=None, gt=0, le=1)
    max_delivery_days: int | None = Field(default=None, gt=0)
    allocation_granularity: Literal["line_item"] = "line_item"
    missing_quote_policy: Literal["disallow", "allow_uncovered"] = "disallow"
    required_supplier_ids: list[UUID] = []
    excluded_supplier_ids: list[UUID] = []


class EventWorkflowState(BaseModel):
    event_id: UUID
    stage: EventStage = EventStage.DRAFT
    supplier_response_ids: list[UUID] = []
    pending_exception_ids: list[UUID] = []
    dataset_version: int = 1
    last_error: str | None = None
