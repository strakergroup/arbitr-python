"""Generated from the pinned OpenAPI snapshot. Do not edit by hand.

Regenerate with: uv run python scripts/generate_models.py
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from arbitr._datetime import UtcDatetime
from arbitr._enums import TolerantStrEnum
from pydantic import Discriminator, Tag
from pydantic import BaseModel, ConfigDict, Field, constr


class FindingType(TolerantStrEnum):
    substitution = "substitution"
    affirmation = "affirmation"
    smoothing = "smoothing"
    term_missing = "term_missing"
    repaired = "repaired"
    rewrite = "rewrite"
    rule_violation = "rule_violation"


class AgentFinding(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    kind: Literal["agent_finding"] = Field("agent_finding", title="Kind")
    id: str = Field(..., title="Id")
    segment_id: str = Field(..., title="Segment Id")
    segment_index: int = Field(..., title="Segment Index")
    locale_code: str | None = Field(None, title="Locale Code")
    agent_code: str = Field(..., title="Agent Code")
    finding_type: FindingType = Field(..., title="Finding Type")
    term: str | None = Field(None, title="Term")
    replacement: str | None = Field(None, title="Replacement")
    source_span: str | None = Field(None, title="Source Span")
    mt_target_span: str | None = Field(None, title="Mt Target Span")
    confidence: float | None = Field(None, title="Confidence")
    suggested_target: str | None = Field(None, title="Suggested Target")


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
    requester: constr(max_length=4000) | None = Field(
        None,
        description="JSON-encoded object naming the person this project is for: tenant_id, external_id, and optional email, name and source. Required when your API key is set to require one.",
        title="Requester",
    )


class CreatedVia(TolerantStrEnum):
    api = "api"
    ui = "ui"


class TenantKind(TolerantStrEnum):
    enterprise = "enterprise"
    workspace = "workspace"


class ConnectionStatus(TolerantStrEnum):
    active = "active"
    disconnected = "disconnected"


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., description="The connection's id.", title="Id")
    provider: str = Field(
        ...,
        description="The chat app, for example `slack`.",
        examples=["slack"],
        title="Provider",
    )
    tenant_id: str = Field(
        ...,
        description="The connected organisation or workspace.",
        examples=["slack:E0789"],
        title="Tenant Id",
    )
    tenant_kind: TenantKind = Field(
        ...,
        description="Whether the tenant is an enterprise or a single workspace.",
        title="Tenant Kind",
    )
    tenant_name: str = Field(..., description="Display name of the tenant.", title="Tenant Name")
    scopes: list[str] = Field(
        ..., description="What keys for this connection may do.", title="Scopes"
    )
    status: ConnectionStatus = Field(
        ..., description="Whether the connection is active.", title="Status"
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
    cycle_start: UtcDatetime | None = Field(None, title="Cycle Start")
    cycle_end: UtcDatetime | None = Field(None, title="Cycle End")


class CreditWallet(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    required: float = Field(..., title="Required")
    available: float = Field(..., title="Available")
    sufficient: bool = Field(..., title="Sufficient")


class DeliverableGeneration(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., title="Id")
    source_file_id: str | None = Field(None, title="Source File Id")
    locale_code: str | None = Field(None, title="Locale Code")
    file_type: str = Field(..., title="File Type")
    name: str | None = Field(None, title="Name")
    created_at: UtcDatetime = Field(..., title="Created At")
    superseded_at: UtcDatetime | None = Field(None, title="Superseded At")


class FindingPage(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    number: int | None = Field(
        1, description="Always 1. Walk with `after`, not `?page=`.", title="Number"
    )
    has_more: bool = Field(..., title="Has More")
    limit: int = Field(..., title="Limit")
    after: str | None = Field(
        None,
        description="Seek token for the next page. Null when no further page exists.",
        title="After",
    )


class FindingSeverity(TolerantStrEnum):
    critical = "critical"
    major = "major"
    minor = "minor"


class FindingStatus(TolerantStrEnum):
    open = "open"
    resolved = "resolved"


class FlagFinding(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    kind: Literal["flag"] = Field("flag", title="Kind")
    id: str = Field(..., title="Id")
    segment_id: str = Field(..., title="Segment Id")
    segment_index: int = Field(..., title="Segment Index")
    locale_code: str | None = Field(None, title="Locale Code")
    severity: FindingSeverity = Field(..., title="Severity")
    category: str | None = Field(None, title="Category")
    description: str | None = Field(None, title="Description")
    status: FindingStatus = Field(..., title="Status")
    suggested_fix: str | None = Field(None, title="Suggested Fix")
    agent_source: str | None = Field(None, title="Agent Source")


class HumanReviewStatus(TolerantStrEnum):
    queued = "queued"
    in_review = "in_review"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    awaiting_payment = "awaiting_payment"
    skipped = "skipped"
    restoring_formatting = "restoring_formatting"


class HumanReviewResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    status: HumanReviewStatus = Field(..., title="Status")
    service_plan: list[str] = Field(..., title="Service Plan")
    charged_tc: float = Field(..., title="Charged Tc")
    requested_at: UtcDatetime = Field(..., title="Requested At")


class LanguageResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    bcp47: str = Field(..., title="Bcp47")
    name: str = Field(..., title="Name")


class ApiKeyMode(TolerantStrEnum):
    live = "live"
    test = "test"


class MeResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    org_id: str = Field(..., title="Org Id")
    mode: ApiKeyMode = Field(..., title="Mode")
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


class RequesterMatchedBy(TolerantStrEnum):
    email = "email"
    linked = "linked"


class RequesterSource(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    app: constr(min_length=1, max_length=200) = Field(
        ...,
        description="The app the request came from.",
        examples=["slack"],
        title="App",
    )
    workspace_id: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Workspace or account id in that app.",
        examples=["T0123"],
        title="Workspace Id",
    )
    location_id: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Channel, conversation or similar id.",
        examples=["C0456"],
        title="Location Id",
    )
    location_name: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Display name of that location.",
        examples=["#marketing"],
        title="Location Name",
    )


class RequesterSourceResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    app: constr(min_length=1, max_length=200) = Field(
        ...,
        description="The app the request came from.",
        examples=["slack"],
        title="App",
    )
    workspace_id: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Workspace or account id in that app.",
        examples=["T0123"],
        title="Workspace Id",
    )
    location_id: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Channel, conversation or similar id.",
        examples=["C0456"],
        title="Location Id",
    )
    location_name: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="Display name of that location.",
        examples=["#marketing"],
        title="Location Name",
    )


class Review(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    status: str | None = Field(
        None,
        description="Human-review state: `queued`, `in_review`, `completed`, `failed`, `cancelled`, `awaiting_payment` (trust credits short, so top up and call `POST /v1/projects/{id}/review/resumptions`), or `skipped` (the workflow has a human stage but nothing was billable, e.g. every file fully matched by translation memory, so no human review ran and nothing is owed). `null` when no human stage was requested.",
        title="Status",
    )
    service_plan: list[str] | None = Field([], title="Service Plan")
    requested_at: UtcDatetime | None = Field(None, title="Requested At")
    completed_at: UtcDatetime | None = Field(None, title="Completed At")


class SourceFileIdentity(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., title="Id")
    file_name: str = Field(..., title="File Name")
    original_file_name: str | None = Field(None, title="Original File Name")
    file_type: str | None = Field(None, title="File Type")
    word_count: int | None = Field(0, title="Word Count")
    character_count: int | None = Field(0, title="Character Count")
    segment_count: int | None = Field(0, title="Segment Count")
    page_count: int | None = Field(None, title="Page Count")


class TextToTranslate(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    ref: constr(min_length=1, max_length=200) = Field(
        ...,
        description="Your id for this text. A text is charged once per ref and target language; send a new ref when the text changes.",
        examples=["T123:C456:1712345678.000100:0"],
        title="Ref",
    )
    text: constr(min_length=1, max_length=30000) = Field(
        ...,
        description="The text to translate, in the request's `format`. At most 30,000 characters.",
        title="Text",
    )
    source_language_code: constr(pattern=r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$") | None = Field(
        None,
        description="Lowercase BCP-47 tag of the text's language. Detected when omitted.",
        examples=["fr-fr"],
        title="Source Language Code",
    )
    target_language_codes: list[constr(pattern=r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")] = Field(
        ...,
        description="Lowercase BCP-47 tags to translate into, at most 10.",
        examples=[["en-us", "fr-ca"]],
        max_length=10,
        min_length=1,
        title="Target Language Codes",
    )


class TextFormat(TolerantStrEnum):
    text = "text"
    html = "html"
    slack = "slack"


class TextUsageType(TolerantStrEnum):
    channel = "channel"
    dm = "dm"
    shortcut = "shortcut"
    api = "api"


class TextTranslationStatus(TolerantStrEnum):
    translated = "translated"
    same_language = "same_language"
    nothing_to_translate = "nothing_to_translate"
    undetermined = "undetermined"
    unsupported = "unsupported"


class TextTranslation(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    target_language_code: str = Field(
        ..., description="Lowercase BCP-47 target tag.", title="Target Language Code"
    )
    status: TextTranslationStatus = Field(
        ...,
        description="`translated`, `same_language` (text already in the target language, or a variant of it such as en-us and en-gb or fr-fr and fr-ca; returned unchanged, not charged), `nothing_to_translate` (only emoji, numbers, punctuation, links or mentions; returned unchanged, not charged), `undetermined` (language not detected; not translated, not charged) or `unsupported` (this language pair can't be translated; not charged).",
        title="Status",
    )
    text: str | None = Field(
        ...,
        description="The translation. The input, unchanged, when it is already right as is (`same_language`, `nothing_to_translate`); null when no translation could be produced (`undetermined`, `unsupported`).",
        title="Text",
    )
    intelligence_credits: float = Field(
        ...,
        description="Credits charged for this text and target; a repeated ref reports its first charge.",
        title="Intelligence Credits",
    )


class TextTranslationResult(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    ref: str = Field(..., title="Ref")
    detected_language_code: str | None = Field(
        ...,
        description="Source language used (given or detected); null when none was given and none was detected.",
        title="Detected Language Code",
    )
    translations: list[TextTranslation] = Field(..., title="Translations")


class UsageUnit(TolerantStrEnum):
    character = "character"
    word = "word"
    page = "page"
    minute = "minute"


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


class ChainOfCustodyResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., title="Id")
    name: str = Field(..., title="Name")
    created_via: CreatedVia = Field(..., title="Created Via")
    created_by: str = Field(..., title="Created By")
    created_by_api_key_id: str | None = Field(None, title="Created By Api Key Id")
    created_at: UtcDatetime = Field(..., title="Created At")
    source_files: list[SourceFileIdentity] = Field(..., title="Source Files")
    deliverables: list[DeliverableGeneration] = Field(..., title="Deliverables")


class DeliverableListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    deliverables: list[ProjectDeliverableResponse] = Field(..., title="Deliverables")
    page: Page


class UnknownFinding(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    kind: str = Field(..., title="Kind")
    id: str = Field(..., title="Id")


def _finding_tag(value: object) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return kind if kind in ("flag", "agent_finding") else "unknown"


class FindingListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    findings: list[
        Annotated[
            Annotated[FlagFinding, Tag("flag")]
            | Annotated[AgentFinding, Tag("agent_finding")]
            | Annotated[UnknownFinding, Tag("unknown")],
            Discriminator(_finding_tag),
        ]
    ] = Field(..., title="Findings")
    page: FindingPage


class LanguageListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    languages: list[LanguageResponse] = Field(..., title="Languages")
    page: Page


class Requester(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    tenant_id: constr(min_length=1, max_length=200) = Field(
        ...,
        description="Your id for the person's organisation or tenant.",
        examples=["E0789"],
        title="Tenant Id",
    )
    external_id: constr(min_length=1, max_length=200) = Field(
        ...,
        description="Your id for the person, unique within the tenant.",
        examples=["U0123"],
        title="External Id",
    )
    email: constr(min_length=1, max_length=320) | None = Field(
        None,
        description="The person's email. When it belongs to a verified member of your organisation, the work is recorded under their account.",
        examples=["ann@example.com"],
        title="Email",
    )
    name: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="The person's display name.",
        examples=["Ann Lee"],
        title="Name",
    )
    source: RequesterSource | None = Field(None, description="Where the request came from.")


class RequesterResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    tenant_id: constr(min_length=1, max_length=200) = Field(
        ...,
        description="Your id for the person's organisation or tenant.",
        examples=["E0789"],
        title="Tenant Id",
    )
    external_id: constr(min_length=1, max_length=200) = Field(
        ...,
        description="Your id for the person, unique within the tenant.",
        examples=["U0123"],
        title="External Id",
    )
    email: constr(min_length=1, max_length=320) | None = Field(
        None,
        description="The person's email. When it belongs to a verified member of your organisation, the work is recorded under their account.",
        examples=["ann@example.com"],
        title="Email",
    )
    name: constr(min_length=1, max_length=200) | None = Field(
        None,
        description="The person's display name.",
        examples=["Ann Lee"],
        title="Name",
    )
    source: RequesterSourceResponse | None = Field(None, description="Where the request came from.")
    user_id: str | None = Field(
        None,
        description="The id of the member of your organisation the work was recorded under, when the email matched one.",
        title="User Id",
    )
    matched_by: RequesterMatchedBy | None = Field(
        None, description="How `user_id` was matched.", title="Matched By"
    )


class TextTranslateRequest(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    texts: list[TextToTranslate] = Field(
        ...,
        description="At most 100 texts, totalling at most 30,000 characters.",
        max_length=100,
        min_length=1,
        title="Texts",
    )
    format: TextFormat | None = Field(
        TextFormat.text,
        description='What kind of text you are sending, for every text in the call. `text`: plain text. `html`: an HTML fragment, returned as HTML with the same tags; mark text to leave alone with `translate="no"` or `class="notranslate"`. `slack`: Slack mrkdwn; mentions, channels, emoji, links and code stay as they are, and link labels are translated.',
        title="Format",
    )
    usage_type: TextUsageType | None = Field(
        TextUsageType.api,
        description="Label shown on usage for this call.",
        title="Usage Type",
    )
    requester: Requester | None = Field(
        None,
        description="The person this call is for. Required when your API key is set to require one. At most 2 KB as JSON.",
    )


class TextTranslateResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    results: list[TextTranslationResult] = Field(..., title="Results")


class UsageRecord(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: str = Field(..., description="Ledger transaction ID.", title="Id")
    created_at: UtcDatetime = Field(
        ..., description="When the charge was made (UTC).", title="Created At"
    )
    project_id: str | None = Field(
        None,
        description="Project the charge was for; null for text translation.",
        title="Project Id",
    )
    description: str | None = Field(None, title="Description")
    usage_type: str | None = Field(
        None,
        description="`channel`, `dm`, `shortcut` or `api` for text translation; `document` for projects; null otherwise.",
        examples=["channel"],
        title="Usage Type",
    )
    source_language_code: str | None = Field(
        None, description="Lowercase BCP-47.", title="Source Language Code"
    )
    target_language_codes: list[str] | None = Field(
        None, description="Lowercase BCP-47 tags.", title="Target Language Codes"
    )
    unit: UsageUnit | None = Field(
        None,
        description="What `quantity` counts. `page` is the project's current page count, which can differ from the count the charge was priced on if pages were later confirmed or changed.",
        title="Unit",
    )
    quantity: float | None = Field(None, title="Quantity")
    file_names: list[str] | None = Field(None, title="File Names")
    intelligence_credits: float | None = Field(0, title="Intelligence Credits")
    trust_credits: float | None = Field(0, title="Trust Credits")
    character_credits: float | None = Field(0, title="Character Credits")
    refunded_credits: float | None = Field(
        0,
        description="Credits later refunded for this charge, in the same wallet. Net spend is the charged credits minus this. Whole-project refunds made by arbitr staff are not linked here yet.",
        title="Refunded Credits",
    )
    api_key_id: str | None = Field(
        None,
        description="API key that made the request; null for web-app usage.",
        title="Api Key Id",
    )
    requester: RequesterResponse | None = Field(
        None,
        description="Who the work was for, when the caller named them. Carries `user_id` and `matched_by` when the email matched a member of your organisation.",
    )


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
    current_status: str | None = Field(
        None,
        description="Present on `not_awaiting_payment` when the project status is known (intelligence-credit resume conflict).",
        title="Current Status",
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
    started_at: UtcDatetime | None = Field(None, title="Started At")
    completed_at: UtcDatetime | None = Field(None, title="Completed At")
    created_at: UtcDatetime | None = Field(None, title="Created At")
    avg_quality_score: float | None = Field(None, title="Avg Quality Score")
    created_by_api_key_id: str | None = Field(None, title="Created By Api Key Id")
    assessment: Assessment | None = None
    review: Review | None = None
    requester: RequesterResponse | None = Field(
        None,
        description="The person the project was created for, when your integration named one.",
    )


class UsageListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    usage: list[UsageRecord] = Field(..., title="Usage")
    page: Page


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    projects: list[ProjectResponse] = Field(..., title="Projects")
    page: Page
