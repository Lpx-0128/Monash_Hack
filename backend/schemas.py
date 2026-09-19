from enum import Enum
from typing import List, Optional, Any
from pydantic import BaseModel, Field

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

class Actor(BaseModel):
    kind: str
    id: Optional[str] = None

class HistoryEvent(BaseModel):
    event_id: str
    run_id: str
    at: str
    type: str
    actor: Actor
    summary: str
    details: Optional[Any] = None

class Metrics(BaseModel):
    ai_calls: int = 0
    ai_assisted_fields: int = 0
    processing_ms: Optional[int] = None
    est_ai_cost_usd: Optional[float] = None

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
    documents: List[Any] = []
    workflow_status: WorkflowStatus
    machine_assessment: Optional[MachineAssessment] = None
    fields: List[Any] = []
    review: Optional[Any] = None
    resolution: Optional[Resolution] = None
    follow_up: FollowUp = FollowUp.NONE
    failure: Optional[Any] = None
    history: List[HistoryEvent] = []
    metrics: Metrics
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
