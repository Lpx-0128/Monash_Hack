from enum import Enum
from typing import List, Optional, Any, Union, Literal
from pydantic import BaseModel, Field, ConfigDict


class EmailCategory(str, Enum):
    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL = "GENERAL"
    SPAM = "SPAM"


class MachineStatus(str, Enum):
    OK = "OK"
    MISMATCH = "MISMATCH"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ReviewReason(str, Enum):
    wrong_doc_type = "wrong_doc_type"
    missing_attachment = "missing_attachment"
    unreadable = "unreadable"
    missing_value = "missing_value"


class CanonicalField(str, Enum):
    shipper = "shipper"
    consignee = "consignee"
    notify_party = "notify_party"
    port_of_loading = "port_of_loading"
    port_of_discharge = "port_of_discharge"
    container_count = "container_count"
    gross_weight_kg = "gross_weight_kg"


class FieldResult(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class NotComparableCause(str, Enum):
    MISSING_VALUE = "MISSING_VALUE"
    UNREADABLE = "UNREADABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNGROUNDED = "UNGROUNDED"
    INVALID_VALUE = "INVALID_VALUE"
    SEMANTIC_UNCERTAIN = "SEMANTIC_UNCERTAIN"
    DOCUMENT_LEVEL = "DOCUMENT_LEVEL"


class WorkflowStatus(str, Enum):
    PROCESSING = "PROCESSING"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReviewUiMode(str, Enum):
    CHOICE = "CHOICE"
    VALUE_INPUT = "VALUE_INPUT"
    ACKNOWLEDGE = "ACKNOWLEDGE"


class ReviewScope(str, Enum):
    FIELD = "FIELD"
    DOCUMENT = "DOCUMENT"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DecisionAction(str, Enum):
    SELECT_OPTION = "SELECT_OPTION"
    PROVIDE_VALUE = "PROVIDE_VALUE"
    ACKNOWLEDGE = "ACKNOWLEDGE"


class ResolvedBy(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    AI = "AI"
    HUMAN = "HUMAN"


class ValueOrigin(str, Enum):
    DOCUMENT_EXTRACTED = "DOCUMENT_EXTRACTED"
    DOCUMENT_CONFIRMED = "DOCUMENT_CONFIRMED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ValueSource(str, Enum):
    DOCUMENT_CONFIRMED = "DOCUMENT_CONFIRMED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class DocumentRole(str, Enum):
    UNKNOWN = "UNKNOWN"
    SI = "SI"
    BL = "BL"
    OTHER = "OTHER"


class Side(str, Enum):
    SI = "SI"
    BL = "BL"


class RunKind(str, Enum):
    EVAL = "EVAL"
    DEMO = "DEMO"


class Channel(str, Enum):
    TELEGRAM = "TELEGRAM"
    DASHBOARD = "DASHBOARD"


class FollowUp(str, Enum):
    NONE = "NONE"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    AWAIT_EXTERNAL = "AWAIT_EXTERNAL"


class ErrorCode(str, Enum):
    REVIEW_ALREADY_CLOSED = "REVIEW_ALREADY_CLOSED"
    STALE_RUN = "STALE_RUN"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    INVALID_VALUE = "INVALID_VALUE"
    VALUE_NOT_FOUND_IN_DOCUMENT = "VALUE_NOT_FOUND_IN_DOCUMENT"
    OVERRIDE_CONFIRMATION_REQUIRED = "OVERRIDE_CONFIRMATION_REQUIRED"
    INVALID_CONFIRMATION = "INVALID_CONFIRMATION"
    OPTION_NOT_FOUND = "OPTION_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"


class HistoryEventType(str, Enum):
    CASE_CREATED = "CASE_CREATED"
    EMAIL_CLASSIFIED = "EMAIL_CLASSIFIED"
    DOCUMENT_PARSED = "DOCUMENT_PARSED"
    AI_EXTRACTION_USED = "AI_EXTRACTION_USED"
    COMPARISON_COMPLETED = "COMPARISON_COMPLETED"
    MISMATCH_VERIFIED = "MISMATCH_VERIFIED"
    REVIEW_CREATED = "REVIEW_CREATED"
    REVIEW_NOTIFIED = "REVIEW_NOTIFIED"
    DECISION_RECEIVED = "DECISION_RECEIVED"
    DECISION_APPLIED = "DECISION_APPLIED"
    DECISION_REJECTED = "DECISION_REJECTED"
    RETRY_TRIGGERED = "RETRY_TRIGGERED"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    REVIEW_SUPERSEDED = "REVIEW_SUPERSEDED"
    CASE_REPROCESSED = "CASE_REPROCESSED"
    CASE_COMPLETED = "CASE_COMPLETED"


# ---------------------------------------------------------------------------
# Locators & Evidence (§7)
# ---------------------------------------------------------------------------

class TextRangeLocator(BaseModel):
    kind: Literal["text_range"] = "text_range"
    start: int
    end: int


class PdfPageLocator(BaseModel):
    kind: Literal["pdf_page"] = "pdf_page"
    page: int


class DocxParagraphLocator(BaseModel):
    kind: Literal["docx_paragraph"] = "docx_paragraph"
    index: int


class DocxTableCellLocator(BaseModel):
    kind: Literal["docx_table_cell"] = "docx_table_cell"
    table: int
    row: int
    column: int


class SheetCellLocator(BaseModel):
    kind: Literal["sheet_cell"] = "sheet_cell"
    sheet: str
    cell: str


Locator = Union[
    TextRangeLocator,
    PdfPageLocator,
    DocxParagraphLocator,
    DocxTableCellLocator,
    SheetCellLocator,
]


class EvidenceRef(BaseModel):
    document_id: str
    locator: Any
    source_text: str


class DocumentRef(BaseModel):
    document_id: str
    role: DocumentRole
    filename: str
    media_type: str
    size_bytes: Optional[int] = None
    content_hash: str
    demo_safe: bool
    parse_status: Literal["OK", "UNREADABLE", "UNSUPPORTED", "NOT_PARSED"]


class OverrideConfirmation(BaseModel):
    review_id: str
    run_id: str
    field: CanonicalField
    side: Side
    proposed_value: Any
    confirmed: bool = True


class FieldValue(BaseModel):
    raw: Optional[str] = None
    normalized: Optional[Union[str, int, float]] = None
    evidence: List[EvidenceRef] = []
    resolved_by: ResolvedBy
    value_origin: ValueOrigin
    grounded: bool
    flags: List[str] = []
    override_confirmations: List[OverrideConfirmation] = []


class FieldComparison(BaseModel):
    field: CanonicalField
    si: Optional[FieldValue] = None
    bl: Optional[FieldValue] = None
    result: FieldResult
    not_comparable_cause: Optional[NotComparableCause] = None
    compared_by: ResolvedBy


class Run(BaseModel):
    run_id: str
    kind: RunKind
    started_at: str
    input_version: str
    config_version: str
    demo_safe: bool


class EmailInfo(BaseModel):
    email_id: str
    from_address: str = Field(alias="from")
    subject: str
    received_at: Optional[str] = None
    category: Optional[EmailCategory] = None
    classified_by: Optional[ResolvedBy] = None
    classification_reason: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class Actor(BaseModel):
    kind: str  # SYSTEM, AI, HUMAN
    id: Optional[str] = None


class HistoryEvent(BaseModel):
    event_id: str
    run_id: str
    at: str
    type: str  # Uses HistoryEventType values
    actor: Actor
    summary: str
    details: Optional[Any] = None


class Metrics(BaseModel):
    ai_calls: int = 0
    ai_assisted_fields: int = 0
    processing_ms: Optional[int] = None
    est_ai_cost_usd: Optional[float] = None


class FailureDetail(BaseModel):
    step: str
    message: str
    attempts: int


class ReviewOption(BaseModel):
    option_id: str
    kind: str  # "DOCUMENT", "VALUE", "ESCAPE"
    label: str
    document_id: Optional[str] = None
    value: Optional[FieldValue] = None


class SourceDocument(BaseModel):
    document_id: str
    filename: str
    media_type: str


class Review(BaseModel):
    review_id: str
    case_id: str
    run_id: str
    status: ReviewStatus
    scope: ReviewScope
    ui_mode: ReviewUiMode
    reason: ReviewReason
    field: Optional[CanonicalField] = None
    side: Optional[Side] = None
    target_role: Optional[Side] = None
    question: str
    context_summary: str
    options: Optional[List[ReviewOption]] = None
    allowed_actions: List[DecisionAction]
    source_documents: List[SourceDocument] = []
    created_at: str
    notified_at: Optional[str] = None
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None


class MachineAssessment(BaseModel):
    status: MachineStatus
    review_reason: Optional[ReviewReason] = None
    has_defect: bool
    defect_fields: List[CanonicalField] = []
    assessed_at: str


class Resolution(BaseModel):
    review_id: str
    run_id: str
    action: DecisionAction
    value_source: Optional[ValueSource] = None
    actor_id: str
    channel: Channel
    user_message: Optional[str] = None
    resolved_at: str
    final_status: MachineStatus
    final_defect_fields: List[CanonicalField] = []


class Case(BaseModel):
    schema_version: str = "2.1.1"
    case_id: str
    run: Run
    email: EmailInfo
    documents: List[DocumentRef] = []
    workflow_status: WorkflowStatus
    machine_assessment: Optional[MachineAssessment] = None
    fields: List[FieldComparison] = []
    review: Optional[Review] = None
    resolution: Optional[Resolution] = None
    follow_up: FollowUp = FollowUp.NONE
    failure: Optional[FailureDetail] = None
    history: List[HistoryEvent] = []
    metrics: Metrics
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None


class CreateCaseRequest(BaseModel):
    email_id: str


class BatchCreateCasesRequest(BaseModel):
    email_ids: List[str]


class BatchCreateCasesResponse(BaseModel):
    total_requested: int
    created: int
    existing: int
    case_ids: List[str]


class CaseSummary(BaseModel):
    case_id: str
    run_id: str
    from_address: str = Field(alias="from")
    subject: str
    category: Optional[EmailCategory] = None
    workflow_status: WorkflowStatus
    machine_status: Optional[MachineStatus] = None
    review_reason: Optional[ReviewReason] = None
    final_status: Optional[MachineStatus] = None
    mismatch_count: int = 0
    has_open_review: bool = False
    run_kind: RunKind
    updated_at: str

    model_config = ConfigDict(populate_by_name=True)


class ReviewListItem(BaseModel):
    review: Review
    case: CaseSummary


class DecisionRequest(BaseModel):
    review_id: str
    run_id: str
    channel: Channel
    actor_id: str
    user_message: Optional[str] = None
    action: DecisionAction
    field: Optional[CanonicalField] = None
    side: Optional[Side] = None
    value: Optional[Any] = None
    option_id: Optional[str] = None
    override_confirmation: Optional[OverrideConfirmation] = None


class NotifiedRequest(BaseModel):
    run_id: str


class BLComparisonStats(BaseModel):
    total: int = 0
    ok: int = 0
    mismatch: int = 0
    needs_review: int = 0


class Stats(BaseModel):
    generated_at: str
    run_kind: RunKind
    total_cases: int = 0
    unclassified: int = 0
    by_category: dict = {}
    bl_comparison: BLComparisonStats = BLComparisonStats()
    by_machine_status: dict = {}
    by_effective_status: dict = {}
    by_workflow: dict = {}
    awaiting_human_now: int = 0
    auto_completed: int = 0
    ai_assisted_cases: int = 0
    ai_calls_total: int = 0
    avg_processing_ms: Optional[float] = None


class GmailSyncRequest(BaseModel):
    username: Optional[str] = None
    app_password: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


class GmailSyncResponse(BaseModel):
    status: str
    fetched: int
    created_cases: List[str] = []
    error: Optional[str] = None


class GmailStatusResponse(BaseModel):
    configured: bool
    connected: bool
    folder: Optional[str] = None
    unseen_count: Optional[int] = None
    error: Optional[str] = None


class GmailClearResponse(BaseModel):
    status: str = "OK"
    deleted_count: int
    message: Optional[str] = None

