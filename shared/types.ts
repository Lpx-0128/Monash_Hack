export type CanonicalField =
  | "shipper" | "consignee" | "notify_party"
  | "port_of_loading" | "port_of_discharge"
  | "container_count" | "gross_weight_kg";
export type EmailCategory = "BL_COMPARISON" | "SI_REQUEST" | "INVOICE_QUERY" | "GENERAL" | "SPAM";
export type MachineStatus = "OK" | "MISMATCH" | "NEEDS_REVIEW";
export type ReviewReason = "wrong_doc_type" | "missing_attachment" | "unreadable" | "missing_value";
export type FieldResult = "MATCH" | "MISMATCH" | "NOT_COMPARABLE";
export type NotComparableCause = "MISSING_VALUE" | "UNREADABLE" | "AMBIGUOUS" |
  "UNGROUNDED" | "INVALID_VALUE" | "SEMANTIC_UNCERTAIN" | "DOCUMENT_LEVEL";
export type WorkflowStatus = "PROCESSING" | "AWAITING_HUMAN" | "BLOCKED_EXTERNAL" | "COMPLETED" | "FAILED";
export type ResolvedBy = "DETERMINISTIC" | "AI" | "HUMAN";
export type ValueOrigin = "DOCUMENT_EXTRACTED" | "DOCUMENT_CONFIRMED" | "MANUAL_OVERRIDE";
export type ValueSource = "DOCUMENT_CONFIRMED" | "MANUAL_OVERRIDE";
export type Side = "SI" | "BL";
export type RunKind = "EVAL" | "DEMO";
export type Channel = "TELEGRAM" | "DASHBOARD" | "VOICE";
export type DocumentRole = "UNKNOWN" | "SI" | "BL" | "OTHER";
export type FollowUp = "NONE" | "CORRECTION_REQUIRED" | "AWAIT_EXTERNAL";
export type ReviewUiMode = "CHOICE" | "VALUE_INPUT" | "ACKNOWLEDGE";
export type ReviewScope = "FIELD" | "DOCUMENT";
export type ReviewStatus = "OPEN" | "CLOSED";
export type DecisionAction = "SELECT_OPTION" | "PROVIDE_VALUE" | "ACKNOWLEDGE";

export type Locator =
  | { kind: "text_range"; start: number; end: number }
  | { kind: "pdf_page"; page: number }
  | { kind: "docx_paragraph"; index: number }
  | { kind: "docx_table_cell"; table: number; row: number; column: number }
  | { kind: "sheet_cell"; sheet: string; cell: string };

export interface EvidenceRef {
  document_id: string;
  locator: Locator;
  source_text: string;
}
export interface DocumentRef {
  document_id: string;
  role: DocumentRole;
  filename: string;
  media_type: string;
  size_bytes: number | null;
  content_hash: string;
  demo_safe: boolean;
  parse_status: "OK" | "UNREADABLE" | "UNSUPPORTED" | "NOT_PARSED";
}
export interface OverrideConfirmation {
  review_id: string;
  run_id: string;
  field: CanonicalField;
  side: Side;
  proposed_value: string | number;
  confirmed: true;
}
export interface FieldValue {
  raw: string | null;
  normalized: string | number | null;
  evidence: EvidenceRef[];
  resolved_by: ResolvedBy;
  value_origin: ValueOrigin;
  grounded: boolean;
  flags: string[];
  // Empty for normal extractions. Inherited for values derived from overrides.
  override_confirmations: OverrideConfirmation[];
}
export interface FieldComparison {
  field: CanonicalField;
  si: FieldValue | null;
  bl: FieldValue | null;
  result: FieldResult;
  not_comparable_cause: NotComparableCause | null;
  compared_by: ResolvedBy;
  confidence?: number | null;
  explanation?: string | null;
}
export interface MachineAssessment {
  status: MachineStatus;
  review_reason: ReviewReason | null;
  has_defect: boolean;
  defect_fields: CanonicalField[];
  assessed_at: string;
  overall_confidence?: number | null;
  explanation?: string | null;
}
export type ReviewOption =
  | { option_id: string; kind: "DOCUMENT"; label: string; document_id: string }
  | { option_id: string; kind: "VALUE"; label: string; value: FieldValue }
  | { option_id: "NONE_OF_THESE"; kind: "ESCAPE"; label: string };
export interface Review {
  review_id: string;
  case_id: string;
  run_id: string;
  status: ReviewStatus;
  scope: ReviewScope;
  ui_mode: ReviewUiMode;
  reason: ReviewReason;
  field: CanonicalField | null;
  side: Side | null;
  target_role: Side | null;
  question: string;
  context_summary: string;
  options: ReviewOption[] | null;
  allowed_actions: DecisionAction[];
  source_documents: { document_id: string; filename: string; media_type: string }[];
  created_at: string;
  notified_at: string | null;
  closed_at: string | null;
  close_reason: "DECISION_ACCEPTED" | "SUPERSEDED" | "TECHNICAL_FAILURE" | null;
}
export interface Resolution {
  review_id: string;
  run_id: string;
  action: DecisionAction;
  value_source: ValueSource | null;
  actor_id: string;
  channel: Channel;
  user_message: string | null;
  resolved_at: string;
  final_status: MachineStatus;
  final_defect_fields: CanonicalField[];
}
export type HistoryEventType =
  | "CASE_CREATED" | "EMAIL_CLASSIFIED" | "DOCUMENT_PARSED" | "AI_EXTRACTION_USED"
  | "COMPARISON_COMPLETED" | "MISMATCH_VERIFIED" | "REVIEW_CREATED" | "REVIEW_NOTIFIED"
  | "DECISION_RECEIVED" | "DECISION_APPLIED" | "DECISION_REJECTED"
  | "RETRY_TRIGGERED" | "PROCESSING_FAILED" | "REVIEW_SUPERSEDED"
  | "CASE_REPROCESSED" | "CASE_COMPLETED";
export interface HistoryEvent {
  event_id: string;
  run_id: string;
  at: string;
  type: HistoryEventType;
  actor: { kind: "SYSTEM" | "AI" | "HUMAN"; id: string | null };
  summary: string;
  details: Record<string, unknown> | null;
}
export interface RunRef {
  run_id: string;
  kind: RunKind;
  started_at: string;
  input_version: string;
  config_version: string;
  demo_safe: boolean;
}
export interface Case {
  schema_version: "2.1.1" | "2.1.2";
  case_id: string; // email_id within the authenticated EVAL or DEMO namespace
  run: RunRef;
  email: {
    email_id: string; from: string; subject: string; received_at: string | null;
    category: EmailCategory | null;
    classified_by: "DETERMINISTIC" | "AI" | null;
    classification_reason: string | null;
  };
  documents: DocumentRef[];
  workflow_status: WorkflowStatus;
  machine_assessment: MachineAssessment | null;
  fields: FieldComparison[];
  review: Review | null; // latest current-run review, including if closed
  resolution: Resolution | null;
  follow_up: FollowUp;
  failure: { step: string; message: string; attempts: number } | null;
  history: HistoryEvent[];
  metrics: {
    ai_calls: number; ai_assisted_fields: number;
    processing_ms: number | null; est_ai_cost_usd: number | null;
  };
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}
export interface CaseSummary {
  case_id: string;
  run_id: string;
  from: string;
  subject: string;
  category: EmailCategory | null;
  workflow_status: WorkflowStatus;
  machine_status: MachineStatus | null;
  review_reason: ReviewReason | null;
  final_status: MachineStatus | null; // effective_status, including last applied result
  mismatch_count: number; // count in current working fields
  has_open_review: boolean;
  run_kind: RunKind;
  updated_at: string;
}
export interface ReviewListItem { review: Review; case: CaseSummary }
interface DecisionBase {
  review_id: string;
  run_id: string;
  channel: Channel;
  actor_id: string; // trusted proxy/bot assertion, verified against authenticated identity
  user_message?: string;
}
export type DecisionRequest =
  | (DecisionBase & {
      action: "PROVIDE_VALUE"; field: CanonicalField; side: Side;
      value: string | number; override_confirmation?: OverrideConfirmation;
    })
  | (DecisionBase & {
      action: "SELECT_OPTION"; option_id: string;
      override_confirmation?: OverrideConfirmation;
    })
  | (DecisionBase & { action: "ACKNOWLEDGE" });
export interface FieldOverrideRequest {
  field: CanonicalField;
  side: Side;
  value: string | number;
  user_message?: string;
  actor_id?: string;
}
export type ErrorCode =
  | "REVIEW_ALREADY_CLOSED" | "STALE_RUN" | "ACTION_NOT_ALLOWED" | "INVALID_VALUE"
  | "VALUE_NOT_FOUND_IN_DOCUMENT" | "OVERRIDE_CONFIRMATION_REQUIRED"
  | "INVALID_CONFIRMATION" | "OPTION_NOT_FOUND" | "NOT_FOUND"
  | "UNAUTHORIZED" | "FORBIDDEN" | "RATE_LIMITED" | "INTERNAL";
export interface ErrorResponse {
  error: { code: ErrorCode; message: string; current_case?: Case };
}
export interface Stats {
  generated_at: string;
  run_kind: RunKind;
  total_cases: number;
  unclassified: number;
  by_category: Record<EmailCategory, number>;
  bl_comparison: { total: number; ok: number; mismatch: number; needs_review: number };
  by_machine_status: Record<MachineStatus, number>;
  by_effective_status: Record<MachineStatus, number>;
  by_workflow: Record<WorkflowStatus, number>;
  awaiting_human_now: number;
  auto_completed: number;
  ai_assisted_cases: number;
  ai_calls_total: number;
  avg_processing_ms: number | null;
}

export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  folder: string | null;
  unseen_count: number | null;
  error: string | null;
}

export interface GmailSyncRequest {
  limit?: number;
  username?: string;
  app_password?: string;
}

export interface GmailSyncResponse {
  status: "OK" | "ERROR";
  fetched: number;
  created_cases: string[];
  skipped_irrelevant?: number;
  error?: string | null;
}

export interface GmailClearResponse {
  status: "OK" | "ERROR" | string;
  deleted_count: number;
  message?: string | null;
}


