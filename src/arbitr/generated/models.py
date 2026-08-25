"""Generated from the pinned OpenAPI snapshot. Do not edit by hand.

Regenerate with: uv run python scripts/generate_models.py
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, constr


class BodyCreateProject(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    file: list[bytes] = Field(
        ...,
        description="One or more source files to translate. Supported formats: .csv, .dita, .ditamap, .docx, .htm, .html, .idml, .json, .markdown, .md, .pdf, .po, .pptx, .properties, .srt, .strings, .ts, .txt, .vtt, .xlf, .xliff, .xlsx, .xml. Note: `.ts` means a Qt Linguist translation file, NOT TypeScript source (TypeScript would be accepted by extension but produce broken output). Each file's leading bytes are inspected: OOXML (.docx/.pptx/.xlsx) and .idml must be ZIP containers; .pdf must carry a PDF signature. A file merely renamed to an allowed extension is rejected.",
        title="File",
    )
    name: constr(max_length=500) = Field(
        ...,
        description="Human-readable project name shown in the arbitr UI",
        title="Name",
    )
    target_language_codes: constr(max_length=2000) = Field(
        ...,
        description="JSON-encoded array of BCP-47 locale codes",
        title="Target Language Codes",
    )
    source_language_code: constr(min_length=1, max_length=64) = Field(
        ...,
        description="BCP-47 locale code, e.g. `en-us`. Required.",
        title="Source Language Code",
    )
    workflow: constr(max_length=2000) = Field(
        ...,
        description="JSON array of workflow stages: AI_TRANSLATION (required), TRANSLATION, EDIT",
        title="Workflow",
    )
    due_date: constr(max_length=32) | None = Field(
        None,
        description="Requested completion date (YYYY-MM-DD); informational only",
        title="Due Date",
    )


class CreditBalanceResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    balance: float = Field(..., title="Balance")
    intelligence_credits: float | None = Field(0, title="Intelligence Credits")
    used_intelligence_credits: float | None = Field(0, title="Used Intelligence Credits")
    trust_credits: float | None = Field(0, title="Trust Credits")
    used_trust_credits: float | None = Field(0, title="Used Trust Credits")
    currency: str | None = Field("credits", title="Currency")
    ic_used_cycle: float | None = Field(0.0, title="Ic Used Cycle")
    tc_used_cycle: float | None = Field(0.0, title="Tc Used Cycle")
    cycle_start: AwareDatetime | None = Field(None, title="Cycle Start")
    cycle_end: AwareDatetime | None = Field(None, title="Cycle End")


class CreditWallet(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    required: float = Field(..., title="Required")
    available: float = Field(..., title="Available")
    sufficient: bool = Field(..., title="Sufficient")


class Status(StrEnum):
    queued = "queued"
    in_review = "in_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    awaiting_payment = "awaiting_payment"


class HumanReviewResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    status: Status = Field(..., title="Status")
    service_plan: list[str] = Field(..., title="Service Plan")
    charged_tc: float = Field(..., title="Charged Tc")
    requested_at: AwareDatetime = Field(..., title="Requested At")


class LanguageResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    bcp47: str = Field(..., title="Bcp47")
    name: str = Field(..., title="Name")


class Mode(StrEnum):
    live = "live"
    test = "test"


class MeResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    org_id: str = Field(..., title="Org Id")
    mode: Mode = Field(..., title="Mode")
    scopes: list[str] = Field(..., title="Scopes")


class Page(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    number: int | None = Field(1, title="Number")
    has_more: bool = Field(..., title="Has More")
    limit: int = Field(..., title="Limit")


class ProjectDeliverableResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., title="Id")
    file_id: str = Field(..., title="File Id")
    file_type: str = Field(..., title="File Type")
    name: str | None = Field(None, title="Name")
    locale_code: str | None = Field(None, title="Locale Code")


class Review(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    status: str | None = Field(None, title="Status")
    service_plan: list[str] | None = Field([], title="Service Plan")
    requested_at: AwareDatetime | None = Field(None, title="Requested At")
    completed_at: AwareDatetime | None = Field(None, title="Completed At")


class FieldError(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    field: str | None = Field(
        ...,
        description="Name of the offending request field, dot-joined for nested values (e.g. `workflow.0`). `null` when the failure has no public field to point at.",
        title="Field",
    )
    message: str = Field(
        ..., description="Human-readable description of the problem.", title="Message"
    )
    type: str = Field(
        ...,
        description="Stable machine-readable error type, for programmatic matching (e.g. `missing`, `value_error`).",
        title="Type",
    )


class AssessmentCredits(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    intelligence: CreditWallet
    trust: CreditWallet | None = None


class DeliverableListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    deliverables: list[ProjectDeliverableResponse] = Field(..., title="Deliverables")
    page: Page


class LanguageListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    languages: list[LanguageResponse] = Field(..., title="Languages")
    page: Page


class ErrorDetail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    code: str = Field(
        ...,
        description="Stable error code. Match on this, not on the message. Codes are never renamed without a major version bump.",
        title="Code",
    )
    message: str = Field(
        ..., description="Human-readable description of the error.", title="Message"
    )
    request_id: str = Field(
        ...,
        description="Identifier for this request; quote it in support requests. Also returned as the `X-Request-ID` header.",
        title="Request Id",
    )
    field_errors: list[FieldError] | None = Field(
        None,
        description="Present on validation failures (`validation_failed`); one entry per rejected field.",
        title="Field Errors",
    )
    supported_formats: list[str] | None = Field(
        None,
        description='Present on unsupported upload-type 422 responses: the full list of accepted file extensions (e.g. ".docx", ".xliff").',
        title="Supported Formats",
    )
    required_scope: str | None = Field(
        None,
        description="Scope the key is missing. Present on `insufficient_scope`.",
        title="Required Scope",
    )
    required: int | float | None = Field(
        None,
        description="Credits required to proceed. Present on `payment_required`.",
        title="Required",
    )
    available: int | float | None = Field(
        None,
        description="Credits currently available. Present on `payment_required`.",
        title="Available",
    )
    shortfall: int | float | None = Field(
        None,
        description="Credits still needed. Present on `payment_required`.",
        title="Shortfall",
    )


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    error: ErrorDetail


class Assessment(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    billable_character_count: int | None = Field(None, title="Billable Character Count")
    due_date: date | None = Field(None, title="Due Date")
    due_date_feasible: bool | None = Field(None, title="Due Date Feasible")
    credits: AssessmentCredits


class ProjectResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., title="Id")
    org_id: str = Field(..., title="Org Id")
    created_by: str = Field(..., title="Created By")
    name: str = Field(..., title="Name")
    source_file_id: str | None = Field("", title="Source File Id")
    source_language_code: str = Field(..., title="Source Language Code")
    word_count: int | None = Field(0, title="Word Count")
    character_count: int | None = Field(None, title="Character Count")
    page_count: int | None = Field(None, title="Page Count")
    status: str = Field(..., title="Status")
    target_language_codes: list[str] | None = Field([], title="Target Language Codes")
    batch_id: str | None = Field(None, title="Batch Id")
    started_at: AwareDatetime | None = Field(None, title="Started At")
    completed_at: AwareDatetime | None = Field(None, title="Completed At")
    created_at: AwareDatetime | None = Field(None, title="Created At")
    avg_quality_score: float | None = Field(None, title="Avg Quality Score")
    created_by_api_key_id: str | None = Field(None, title="Created By Api Key Id")
    assessment: Assessment | None = None
    review: Review | None = None


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    projects: list[ProjectResponse] = Field(..., title="Projects")
    page: Page
