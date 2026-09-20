# Shared System Contract — v2.1.2

**Date:** 20 September 2026

**Authority:** This document governs [PRD 1 — Backend Automation & Intelligence Layer](./prd-1-backend.md) and [PRD 2 — Interaction / Frontend Layer](./prd-2-interaction.md). It also governs [PRD 3 — Voice & Attention Orchestration Layer](./prd-3-voice-attention.md). No PRD may redefine its types, semantics, invariants, or API behavior.

**Status:** Coordinated adoption pending. v2.1.1 remains the deployed implementation baseline until A/B/C approve and deploy the v2.1.2 migration in §7.3. This document specifies the next target contract; editing it does not enable VOICE in existing validators. Organizer verification and voice integration gates remain explicit; no completed team sign-off is claimed.

## 1. Purpose, precedence, and source basis

Automate shipping-inbox triage and compare the Shipping Instruction (SI, the reference) against the draft Bill of Lading (BL). Use deterministic code first, AI for interpretation, deterministic validation next, and human judgment only where needed.

The product promise is **“Don’t monitor AI. Let it chase you.”** Users receive proactive requests or notices and can use the lowest-friction safe channel. Some problems require a corrected external document; the promise is freedom from constant monitoring, not universal resolution inside Telegram.

On coordinated adoption, this revision supersedes v2.1.1 and v2.1 and replaces v2.0 and the older contract, revision logs, and conflicting PRD passages. It preserves backend-owned truth, polling, Telegram plus dashboard with the separately gated voice extension, immutable machine assessments per run, separate operational resolution, and separate EVAL/DEMO execution. It does not reintroduce an event bus, case_version, separate evidence service, or separate audit API.

Source basis:

- The referenced [Create Two PRDs conversation](chatgpt-conversation://6aae5955-a0e4-83ec-9e1c-a261356cb529), including the latest accepted reviewer response.
- The retrieved attachment titled “Shared System Contract — v2.0” and the latest attached reviewer report, beginning “The architecture is sound, but the documents are not ready to freeze.”
- The attached preliminary judging rubric. Earlier conversation findings report the participant vocabulary and submission shape adopted below. For v2.1.1, the problem-statement PDF, participant README, loader, submission template, all inbox record shapes, archive inventory, and selected source examples were inspected directly. No pipeline accuracy evaluation or private answer-key inspection was performed.
- [Organizer problem statement and data folder](https://drive.google.com/drive/folders/1ouOrFF6GMKvJDaX_asN8R6v467W7P8Df), retained as a source location, not permission to use organizer-only materials.

Only participant-facing materials and the permitted evaluation interface may support implementation and tuning. Do not inspect or use private answer keys or organizer-only ground truth.

## 2. Ownership and change control

| Role | Responsibility |
|---|---|
| A — Document Intelligence | Ingestion adapter, parsing, extraction, evidence, grounding, normalization, comparison, mismatch verification, dependency recomputation |
| B — Platform + Validation | Cloud execution, state, API, reviews, durable work, retries, runs, access boundaries, export, evaluation harness, validation report |
| C — Interaction + Submission | Dashboard, Telegram, voice adapter and attention policy, shared routing, notification delivery, confirmation UX, interaction tests; submission packaging after frontend MUST work |

The backend owns truth and execution. Interaction clients display API data and submit structured decisions; they never read/write backend storage directly or independently decide shipping outcomes.

A PRD may change libraries, layouts, prompts, internal storage, or implementation order without contract amendment if all shared obligations still hold. Any changed enum, wire shape, endpoint, state rule, evidence meaning, privacy boundary, or export behavior requires a coordinated contract revision approved by A/B/C. Additive optional fields must also be documented and validated. Do not claim team approval until obtained.

Each role completes its MUST work before SHOULD/OPTIONAL work. A role finishing early helps unresolved integration, validation, or submission work before adding polish.

Checkpoints: shared types/mocks approved; first real Case rendered; first real human-review handshake; repeatable end-to-end rehearsal. The handshake occurs immediately after the minimal backend slice, before broad accuracy tuning.

## 3. Closed vocabulary

| Type | Values |
|---|---|
| EmailCategory | BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM |
| MachineStatus | OK, MISMATCH, NEEDS_REVIEW |
| ReviewReason | wrong_doc_type, missing_attachment, unreadable, missing_value |
| CanonicalField (also review ordering) | shipper, consignee, notify_party, port_of_loading, port_of_discharge, container_count, gross_weight_kg |
| FieldResult | MATCH, MISMATCH, NOT_COMPARABLE |
| NotComparableCause | MISSING_VALUE, UNREADABLE, AMBIGUOUS, UNGROUNDED, INVALID_VALUE, SEMANTIC_UNCERTAIN, DOCUMENT_LEVEL |
| WorkflowStatus | PROCESSING, AWAITING_HUMAN, BLOCKED_EXTERNAL, COMPLETED, FAILED |
| ReviewUiMode / ReviewScope | CHOICE, VALUE_INPUT, ACKNOWLEDGE / FIELD, DOCUMENT |
| ReviewStatus / DecisionAction | OPEN, CLOSED / SELECT_OPTION, PROVIDE_VALUE, ACKNOWLEDGE |
| ResolvedBy | DETERMINISTIC, AI, HUMAN |
| ValueOrigin | DOCUMENT_EXTRACTED, DOCUMENT_CONFIRMED, MANUAL_OVERRIDE |
| ValueSource (human decisions) | DOCUMENT_CONFIRMED, MANUAL_OVERRIDE |
| DocumentRole / Side | UNKNOWN, SI, BL, OTHER / SI, BL |
| RunKind / Channel | EVAL, DEMO / TELEGRAM, DASHBOARD, VOICE |
| FollowUp | NONE, CORRECTION_REQUIRED, AWAIT_EXTERNAL |

UNKNOWN is valid before document-role determination. Email category and classified_by are null before classification, including a failure before classification. They must be non-null once a machine assessment exists. Human input does not rewrite the run's classification.

NOT_READY is an internal actionability diagnostic only. It is not a new category, machine status, workflow state, or export bypass. Until organizer mapping is verified, a BL_COMPARISON email follows normal assessment rules even if that diagnostic is set. Every required EVAL email still needs the required category/status output. No actionable-skip fixture may be enabled without a complete, verified mapping covering fields, workflow, review, follow-up, and export.

## 4. Grounding, provenance, and comparisons

### 4.1 Grounded means all three gates pass

- **G1:** The quoted source and location exist in the immutable parsed document for this run.
- **G2:** The label, table structure, or nearby context supports the intended canonical field.
- **G3:** The normalized value is derivable from that evidence using the approved field policy.

A gross-weight value cannot be grounded by matching digits inside a seal number or net-weight field. Apply the same gates to AI extractions, deterministic extractions, human document-confirmed values, and selectable candidates.

Evidence is a list because totals, component rows, and references may depend on multiple locations. Keep original wording and every contributing location. Derived “same as consignee” values cite both the reference statement and the consignee evidence.

### 4.2 Comparability

Automated comparison requires, on each side: a present, type-valid, grounded value, one unambiguous canonical result (direct or approved aggregation), and no unresolved conflict.

Operational comparison after human intervention permits either:

1. the grounded document value above; or
2. an explicitly confirmed, type-valid manual override.

An override remains grounded=false, value_origin=MANUAL_OVERRIDE, resolved_by=HUMAN. It never becomes document evidence and never changes the frozen machine assessment. A dependency derived from an override must retain the override lineage and remain ungrounded; deterministic derivation does not launder its provenance.

Blank required values on both sides are NOT_COMPARABLE. Numeric comparison is deterministic. AI semantic equivalence is disabled in the scored path by default; any proposed enablement needs measured validation and resolution of the organizer uncertainty mapping.

### 4.3 Roll-up and reason priority

Apply to the automated pass and, separately, to current operational fields:

1. Non-BL category: OK, no comparison fields or defects.
2. Document-level problem: NEEDS_REVIEW.
3. Any NOT_COMPARABLE field: NEEDS_REVIEW.
4. Otherwise any MISMATCH: MISMATCH.
5. Otherwise: OK.

NEEDS_REVIEW always has has_defect=false and defect_fields=[] in the machine/export shape. Confirmed mismatches remain visible in fields even when another uncertainty takes precedence. MISMATCH has nonempty defect_fields and no review_reason. OK has no reason or defects.

| Condition | Reason |
|---|---|
| Required attachment genuinely absent | missing_attachment |
| Attachments exist but expected role/type cannot be established | wrong_doc_type |
| Content is unreadable, or located content cannot be reliably interpreted | unreadable |
| Required value absent from a readable document | missing_value |

Priority: missing_attachment > wrong_doc_type > unreadable > missing_value. Internal causes remain more detailed. Readable ambiguity uses the documented provisional “cannot reliably interpret” mapping; verify it through participant-facing means before scored release. Do not invent a fifth organizer reason.

## 5. Review construction and bounded interaction

Only one OPEN review per active case is permitted.

| Situation | Scope and mode | Workflow |
|---|---|---|
| Readable documents, at most two distinct unresolved fields | FIELD / VALUE_INPUT, or CHOICE with at least two candidates | AWAITING_HUMAN |
| Unassigned plausible documents can fill a role | DOCUMENT / CHOICE with target_role | AWAITING_HUMAN |
| Missing attachment, wholly unreadable document, unusable type, more than two unresolved fields, exhausted review budget | DOCUMENT / ACKNOWLEDGE | BLOCKED_EXTERNAL |

The two-field cap counts **distinct canonical fields requiring human input across the entire run**, not messages, sides, or only the currently outstanding set. Review fields in canonical order; when both sides are unresolved, SI precedes BL.

v2.1 bounded defaults: at most two accepted field-input/choice decisions per canonical field, with at most one per side; at most one document-role choice per target role, hence at most two per run. Further unresolved work becomes BLOCKED_EXTERNAL. Invalid/rejected submissions do not consume accepted-decision budgets or create new reviews. Rate-limit invalid requests. These finite defaults operationalize the agreed requirement to prevent review loops.

| Mode | Allowed actions | Escape |
|---|---|---|
| CHOICE | SELECT_OPTION | Required reserved option_id=NONE_OF_THESE |
| VALUE_INPUT | PROVIDE_VALUE, ACKNOWLEDGE | “I can’t tell” |
| ACKNOWLEDGE | ACKNOWLEDGE | Acknowledges the external action needed |

FIELD reviews require field and side. DOCUMENT CHOICE requires target_role=SI or BL. A document may not occupy both roles. Candidate values retain their evidence; unsupported candidates require the same explicit override confirmation as typed values. NONE_OF_THESE and ACKNOWLEDGE close the review and lead to BLOCKED_EXTERNAL without pretending verification succeeded.

## 6. State and transition semantics

machine_assessment is immutable after the automated pass. fields is the mutable working comparison. resolution describes the latest applied human action and resulting operational outcome; older actions remain in accepted-decision records and history.

effective_status = resolution.final_status if present, otherwise machine_assessment.status, otherwise null.

follow_up is derived in this order: BLOCKED_EXTERNAL → AWAIT_EXTERNAL; effective_status=MISMATCH → CORRECTION_REQUIRED; otherwise NONE. The UI also shows workflow, so a technical failure is never hidden by an older effective result.

| Event | Durable result / subsequent processing |
|---|---|
| New run | PROCESSING; category, assessment, resolution initially null |
| First automated pass, OK/MISMATCH | Freeze assessment; COMPLETED; completed_at set |
| First pass, actionable uncertainty | Freeze NEEDS_REVIEW; OPEN review; AWAITING_HUMAN |
| First pass, external block | Freeze NEEDS_REVIEW; OPEN acknowledgment review; BLOCKED_EXTERNAL |
| Valid decision accepted | Persist decision + close review + pending work atomically; PROCESSING; return 202 |
| Applied value/choice resolves all uncertainty | Write resolution; COMPLETED; completed_at set |
| First of two reviews resolves only part | resolution.final_status=NEEDS_REVIEW; next OPEN review; AWAITING_HUMAN |
| Applied acknowledgment/escape | Write resolution with NEEDS_REVIEW and empty final_defect_fields; BLOCKED_EXTERNAL; review CLOSED |
| Retryable technical failure | One automatic retry of the failed work unit |
| Retry exhausted / non-retryable technical failure | FAILED; failure recorded; original assessment and accepted decisions retained |
| Reprocess | Atomically supersede old OPEN review, replace active run pointer, enqueue new run; PROCESSING |
| Stale/duplicate decision | 409; no accepted decision, new job, or case mutation |

Acknowledgment also uses the brief PROCESSING acceptance envelope before the worker records BLOCKED_EXTERNAL. This makes all accepted decision endpoints consistent. An acknowledged block no longer counts as awaiting a user decision but remains an external block.

completed_at is set only for operational COMPLETED, never merely because an assessment exists. It is null for a new run and for every non-completed current run. During pending resumption, a prior resolution may remain visible as the last applied result; label it accordingly, never as the result of the newly accepted decision.

### Mandatory invariants

1. A null assessment is allowed only before successful first-pass finalization, in PROCESSING or FAILED. A finalized assessment is never cleared by resumption failure.
2. Assessment shape follows §4.3; category/classified_by are non-null if assessment exists.
3. AWAITING_HUMAN has exactly one OPEN CHOICE/VALUE_INPUT review belonging to the active run.
4. BLOCKED_EXTERNAL has a review: OPEN ACKNOWLEDGE or a CLOSED review documenting the block/escape.
5. COMPLETED has no OPEN review and effective_status is OK or MISMATCH.
6. FAILED has failure details and no OPEN review; accepted decisions and prior assessment survive.
7. Settled BL cases have exactly seven unique canonical fields; non-BL cases have fields=[]. PROCESSING/FAILED may retain partial fields.
8. NOT_COMPARABLE iff not_comparable_cause is non-null.
9. CLOSED review has closed_at and close_reason; OPEN review has neither.
10. CHOICE has unique options including exactly one NONE_OF_THESE; payload targeting follows §5.
11. DOCUMENT_CONFIRMED values pass G1–G3; MANUAL_OVERRIDE values remain ungrounded with auditable confirmation lineage.
12. follow_up equals its derivation; completed_at is non-null iff workflow is COMPLETED.
13. Every mutation checks active run identity at commit time; stale workers cannot write into a newer run.
14. Public access requires both DEMO scope and explicit demo-safe authorization for the case and every referenced document.
15. Export eligibility depends on a finalized automated assessment, not operational completion.
16. email.received_at is always present, with either a valid source receipt timestamp or null. Missing receipt time is valid metadata absence in every workflow state; it cannot by itself cause FAILED, NEEDS_REVIEW, or an export failure.

## 7. Authoritative wire types

Known JSON timestamps are UTC ISO-8601 strings; email.received_at alone may be null when the source provides no receipt time. IDs are opaque strings. All listed properties are required unless marked optional. null is explicit absence. TypeScript definitions plus the semantic invariants define the wire contract; one shared runtime validator must enforce both. OpenAPI/code generation is optional.

~~~ts
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
}
export interface MachineAssessment {
  status: MachineStatus;
  review_reason: ReviewReason | null;
  has_defect: boolean;
  defect_fields: CanonicalField[];
  assessed_at: string;
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
  schema_version: "2.1.2";
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
  actor_id: string; // trusted interaction-service assertion, verified against authenticated identity
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
~~~

Locator conventions: text offsets and DOCX indices are zero-based; text end is exclusive; PDF pages are one-based; sheet cells use A1 notation. Text offsets use the parser's documented Unicode code-point sequence. Store the parsed artifact used for evidence; changing parsers cannot silently reinterpret old locators.

String/number normalized types are narrowed by the field-policy table in PRD 1. Manual typed weight is kg in canonical form; document text may contain convertible units. Finite positive values only for numeric fields. Missing values may be null; never manufacture placeholder strings as comparable values.

History is embedded, with run_id on every event. Case history may include earlier runs in the same namespace; document links and payloads must still pass scope authorization. No chain-of-thought or hidden model reasoning is stored.

### 7.1 Receipt time and system activity times

The inspected participant records contain email_id, from, subject, body, and attachments, but none of the 520 records provides received_at. The participant-to-Case mapper must emit received_at=null. It must not block conversion for this absence, omit the required key, use an empty string/epoch sentinel, invent a receipt time, or infer one from quoted email history.

A future source that provides a trustworthy receipt timestamp may populate received_at after normalization. A malformed supplied timestamp is a source-validation issue, distinct from an absent timestamp; report it explicitly rather than silently converting it to null.

- Case.created_at: when the system first creates the case in its namespace. Stable across reprocessing.
- Case.updated_at: the most recent case update.
- run.started_at: the start of the current run.
- completed_at: operational completion under §6.

Never relabel these system timestamps as email receipt time. No additional ingestion timestamp is required for this amendment. Synthetic fixtures may contain explicitly fictional receipt times or null, but participant-derived cases must preserve source absence.

### 7.2 Historical v2.1.1 receipt-time adoption

The following records the earlier migration. For the current target version, use §7.3; retained v2.1.1 references in companion implementation plans describe the pre-voice baseline and do not override §7.3.

Update the shared types, runtime validator, mapper, simulator responses, dashboard, and fixtures together to schema_version="2.1.1". Known timestamps remain valid; null is newly permitted, so strict v2.1 consumers require updating. This editorial patch is not a claim of wire compatibility with an unmodified validator.

Do not maintain a separate provisional simulator schema. Remove the earlier missing-receipt blocking workaround once the coordinated amendment is adopted. Keep historical run/snapshot artifacts unchanged; if a legacy case is migrated, preserve timestamp provenance and do not manufacture missing metadata.

### 7.3 Coordinated v2.1.2 voice adoption

VOICE is an additional interaction channel, not a source of business truth. Deploy shared types/runtime validators, authorized voice-service identity, accepted-decision channel persistence and consumers, schema_version emission, simulator and fixtures together. The target Case schema_version is "2.1.2". Older strict clients may reject the new literal or channel; this is not a promise of compatibility with unmodified v2.1.1 code. Preserve historical snapshots and provenance. Do not silently rewrite frozen EVAL artifacts.

A/B/C approval and a tested backend capability are required before enabling real VOICE submissions. Until then, existing deployment paths remain on their coordinated baseline; voice experiments may perform authorized reads or log explicitly synthetic proposals. They must not send VOICE to an old validator or mislabel a call as TELEGRAM. No runtime migration is performed by this documentation revision.

Voice uses the same DecisionRequest union, actions, review budgets, grounding/override rules, durable acceptance and run guards. No new business endpoint, workflow status, review mode or urgency field is introduced. Existing AcceptedDecision.channel stores VOICE after adoption; business history retains its existing event vocabulary. Provider/call metadata remains interaction-owned.

## 8. API, asynchronous work, and concurrency

All business endpoints use /api/v1 and authenticated, server-enforced scope. Health routes are /health and /ready and expose no dataset content.

| Method and path | Request / response |
|---|---|
| GET /cases | CaseSummary[]; filters workflow_status, category, final_status, has_open_review, run_kind |
| GET /cases/{case_id} | Current Case in authorized namespace |
| POST /cases | {email_id:string}; starts approved DEMO fixture; 202 Case(PROCESSING) for new work |
| POST /cases/{case_id}/reprocess | Empty body; authorized new DEMO run; 202 Case(PROCESSING) |
| GET /reviews | ReviewListItem[]; filters status, notified, run_kind; default current runs only |
| POST /reviews/{review_id}/notified | {run_id:string}; idempotently records server notified_at; 200 Review |
| POST /reviews/{review_id}/decision | DecisionRequest; 202 Case(PROCESSING) after durable acceptance |
| GET /documents/{document_id}/content | Authorized original bytes, safe filename/content type; never arbitrary storage path |
| GET /stats | Stats for latest run per case in authorized selected scope |
| GET /health, GET /ready | Liveness/readiness, no auth, no sensitive details |

GET requests never mutate notification state. A public run_kind=EVAL parameter cannot widen scope.

Duplicate POST /cases for an existing active DEMO case returns 200 with its current Case in whatever state it actually has; it does not reset the case. Every explicit successful reprocess request starts a new run, including repeated clicks. Disable repeat clicks and do not automatically retry a timed-out reprocess: refetch first. This is distinct from duplicate decision semantics, where first acceptance wins and later attempts return 409.

EVAL ingestion/reprocessing/export are private operator/batch operations outside public create/replay routes. Maintain separate case namespaces for EVAL and DEMO even if email_id strings coincide; active run identity and one-open-review constraints apply within that namespace. Public fixtures must never alias private cases by raw ID.

### Durable decision acceptance

Authenticate and authorize first. Validate request path/body IDs, current run, OPEN status, action, target field/side, option membership, types, and grounding. Missing grounding returns 422 without closing the review; confirmed overrides must bind the exact review_id, run_id, field, side, and canonical proposed_value. Editing the value invalidates the confirmation. Ignore any client claim of grounded=true; the server computes provenance.

In one transaction:

1. Recheck the active run and OPEN review under a lock/conditional update.
2. Persist the normalized accepted decision, trusted actor, channel, confirmation, and evidence.
3. Close the review with DECISION_ACCEPTED.
4. Insert durable pending-resumption work and a decision-accepted history event.
5. Set PROCESSING and commit.

Only then return 202. The worker applies accepted decisions idempotently and persists result/history together. A crash after acceptance must not require human re-entry. Persist job status, attempts, and completion identity; on restart recover pending/interrupted work. A small durable work table and one worker loop suffice.

After retry exhaustion, keep the unapplied accepted decision and work record for operator recovery; the user must not resubmit it. Operator retry resumes that work under the same active run. Explicit reprocess creates a fresh run and retains the old record for audit without silently carrying human overrides into the new automated assessment.

Every processing write, including finalization, field updates, review creation, retries, and pending-decision application, conditionally checks active run_id at commit. Reprocess atomically closes old OPEN reviews as SUPERSEDED, writes REVIEW_SUPERSEDED history, switches active run, and records new pending work. Older workers discard stale results.

### Error behavior

401 UNAUTHORIZED; 403 FORBIDDEN for denied scope (404 NOT_FOUND may conceal object existence); 404 NOT_FOUND; 409 REVIEW_ALREADY_CLOSED or STALE_RUN; 422 for action/type/option/grounding/confirmation errors; 429 RATE_LIMITED; 500 INTERNAL.

Check an accessible CLOSED review before stale-run details so old superseded buttons normally return REVIEW_ALREADY_CLOSED. Do not reveal a current_case outside the caller's scope. A timeout is not proof a decision failed: refetch the Case, preserving the pending UI until acceptance is known.

## 9. Recalculation and external recovery

Recompute the changed value and its dependencies, then compare and roll up again.

- Consignee change invalidates notify_party when derived from “same as consignee.”
- Document assignment invalidates all values from that document and reruns parse/extract/ground/normalize/compare as needed.
- Totals use all contributing lines or one trusted total, never both.
- Preserve source hashes, dependency links, and override lineage.
- Each review is checked against the recomputed state and the run's review budget.

For BLOCKED_EXTERNAL, the MVP operator obtains corrected input, stores a new immutable source version through a controlled private workflow, and starts a new authorized run. Reprocessing identical missing/unreadable sources does not repair them. Public replacement upload is optional.

## 10. Proactive notifications and restart-safe routing

One notifier instance for MVP. Poll reviews and cases every 3–5 seconds with bounded backoff on failures. Telegram uses long polling; persist the update cursor and processed-update records. Persist these interaction-owned records:

- Telegram chat_id/message_id ↔ review_id/run_id/case_id.
- Individual review delivery keyed by run_id/review_id/recipient.
- Non-review delivery keyed by run_id/notification_type/recipient.
- Pending confirmation bound to actor, review, run, field, side, and value.
- Notification queue state and retry attempts.

Notification types: REVIEW_REQUIRED, MISMATCH_DETECTED, TECHNICAL_FAILURE. The backend creates reviews only for decisions/inputs. A completed confirmed mismatch needs a correction notice without a new review. A technical failure notifies the team/operator rather than asking a business user to troubleshoot.

For a case with both confirmed mismatch and outstanding uncertainty, include the known discrepancy in review context; send the standalone mismatch notice when the operational comparison settles as MISMATCH. Deduplicate it within the run.

Send the review message, persist its mapping/delivery record, then mark the review notified. On restart, a persisted successful delivery can be marked without sending again. A crash between external send and local persistence may cause an occasional duplicate notification; do not claim exactly-once delivery. Duplicate decisions are still prevented by the backend transaction.

A digest says how many cases need attention. It never marks individual reviews notified. Send individual messages only under rate limits/selection and mark them only after actual send. Before queued delivery, verify the review is still OPEN in the active run.

Never apply bare typed values to whichever review happens to be open. Require reply-to a mapped message or explicit case/review selection. Old/closed/superseded mappings are rejected. Confirmation buttons are bound to their exact pending proposal, not a global “yes.”

Telegram documents are fetched server-to-server with a scoped credential and uploaded using sendDocument. Never expose bearer credentials in links. Source snippets and a responsive dashboard deep link accompany the review; evidence crops remain optional.

### 10.1 Voice routing, confirmation and notification boundary

PRD 2 owns the shared interaction service and existing notifier. PRD 3 adds a voice adapter and attention policy through that service; it must not create an independent shipping workflow engine or a competing notifier. Voice Task Inbox classifications and call lifecycle states are interaction-owned and are not added to backend enums.

Authenticate the actor before disclosing protected case information or accepting a voice action. Caller ID alone is insufficient. Use a trusted authenticated pairing/session, such as a short-lived challenge approved in the enrolled Telegram account. Validate provider callbacks and replay handling; the trial spike's unsigned capability URL is not production authentication. Assert actor_id only from the authenticated session and enforce authorized case/run/document scope server-side.

Explicitly select the current review and bind a spoken proposal to actor, case, review_id, run_id, action, option_id or canonical value, and applicable field/side/unit. Read back the exact proposed action and obtain explicit confirmation before any voice mutation. Silence, ambiguity, correction, expired/disconnected sessions and unrelated yes responses cannot authorize submission. A changed proposal or run invalidates confirmation. Unsupported values/candidates still require the exact OverrideConfirmation tuple and remain ungrounded; model assertions cannot supply confirmation.

Deferral leaves the review unchanged. ACKNOWLEDGE and NONE_OF_THESE are intentional contract actions with external-block semantics, not synonyms for postponement. Evidence requirements are unchanged by channel: selecting between uncertain scanned values still requires evidence inspection or an explicitly confirmed allowed override.

For this rollout, notified_at retains its individual Telegram review-message delivery meaning. Phone ringing, answered calls, inbound summaries and voice attempts do not mark a review notified or suppress Telegram evidence/fallback delivery. Keep per-channel attempt/delivery records in the interaction service. A broader channel-neutral notified meaning requires a later coordinated semantic revision.

Keep call/proposal/replay/submission records durable. On restart or lost response, reconcile backend state before retry; do not replay an old voice proposal against a new review. 202 means accepted and resuming, not completed. Backend commit-time concurrency guards remain authoritative across all three channels.

## 11. EVAL isolation and frozen submission snapshots

Public dashboard credentials and the bot can access only explicitly authorized demo-safe cases/runs/documents across list, detail, review, decision, stats, content, create, and reprocess routes. A DEMO label alone does not authorize organizer documents. Enforce this server-side even when a proxy holds a token.

Keep EVAL credentials and routes private. Voice actors use authenticated scoped sessions under §10.1; Telegram actors are authenticated/allowlisted; dashboard actors use trusted sessions or an explicit demo guest identity restricted to safe fixtures. actor_id is never trusted merely because it appears in browser JSON.

A submission snapshot is a pure export of successfully finalized automated EVAL assessments, independent of workflow_status. A valid frozen NEEDS_REVIEW assessment is exportable while AWAITING_HUMAN or BLOCKED_EXTERNAL, and remains valid after a later human-resumption failure.

The release manifest pins:

- Dataset/input version and required email-ID set.
- Configuration version (code, model, prompts, parser, normalization/alias policy).
- Selected successful EVAL run_id per email.
- Snapshot creation time and content hash.
- Any earlier successful run reused and the later failed run it replaces.

An earlier successful assessment may be reused only when its input/config versions match the intended release and the manifest explicitly identifies it. Never silently use an arbitrary old result. The exporter must fail with a missing/invalid-ID report if any required email lacks an eligible assessment; it neither omits emails nor fabricates unreadable for a technical exception. A failed export produces no release-ready snapshot.

The organizer entry is category plus the frozen assessment fields, excluding assessed_at and internal metadata:

~~~json
{
  "email_055": {
    "category": "BL_COMPARISON",
    "status": "NEEDS_REVIEW",
    "review_reason": "unreadable",
    "has_defect": false,
    "defect_fields": []
  }
}
~~~

DEMO replay and human operational resolution cannot change an existing snapshot. No manual override enters scored output.

## 12. Metrics and honest UI meaning

Stats use the latest run per case in the selected authorized scope. Public dashboards are DEMO-only. Validation reports are EVAL-only; any all-run report must be separately labelled.

- by_machine_status and bl_comparison use the frozen assessment; unassessed runs are not counted as OK.
- by_effective_status uses the last applied resolution or assessment. PROCESSING/FAILED remains independently visible.
- awaiting_human_now counts OPEN reviews in AWAITING_HUMAN or BLOCKED_EXTERNAL.
- auto_completed counts current COMPLETED runs with zero reviews created in that run.
- ai_assisted_cases counts current runs with ai_calls>0; ai_assisted_fields counts unique field/side extraction targets, at most 14 for BL.
- processing_ms measures active processing time, excluding time waiting for a human. Cost is null when unavailable, never fabricated.
- resolved_by distribution is per populated current field-side value; inherited manual overrides remain visible via provenance.

Do not infer a credible mobile-resolution percentage from one to three demonstrations.

## 13. Shared fixtures and acceptance scenarios

Mocks must be complete Case payloads satisfying §7 and all invariants; abridged snippets are not fixtures. Build: processing/null-category; clean match; mismatch; non-BL; field value input; field candidate choice; document choice; blocked-open; blocked-acknowledged; human-resolved; two sequential reviews; failed-before-assessment; failed-after-accepted-decision; superseded review; empty/ populated stats; known-receipt and unknown-receipt cases across processing and settled states.

Required end-to-end checks:

| ID | Scenario and expected result |
|---|---|
| AC-01 | Type-valid unsupported value is rejected until exact override confirmation; operational comparison then completes, override stays ungrounded, assessment unchanged |
| AC-02 | Two fields resolve sequentially, with SI before BL when both sides fail; first resolution remains NEEDS_REVIEW |
| AC-03 | Simultaneous dashboard/Telegram decision: exactly one durable acceptance, other request 409 |
| AC-04 | Crash after acceptance: decision survives; restart resumes without human re-entry |
| AC-05 | Reprocess during processing: old work cannot mutate the new run; old reviews superseded |
| AC-06 | Old Telegram reply or confirmation cannot affect the next review |
| AC-07 | Public requests for EVAL cases, reviews, stats, content, or replay fail, including guessed IDs and cross-scope links |
| AC-08 | Valid EVAL NEEDS_REVIEW exports while awaiting human; missing assessment blocks export |
| AC-09 | Old run writes after reprocess are rejected at commit, including review creation and finalization |
| AC-10 | Confirmed mismatch with no review produces one logical correction notification per run |
| AC-11 | Seal-number digits cannot ground gross weight for machine extraction, human entry, or candidate selection |
| AC-12 | Consignee/reference and total/component recomputation preserve dependencies, evidence, and override lineage |
| AC-13 | Whole-document failure or third distinct unresolved field blocks externally; acknowledgment does not mark verification complete |
| AC-14 | Notification restart/digest handling preserves routing; occasional send duplicates never produce duplicate decisions |
| AC-15 | Earlier successful EVAL reuse requires matching input/config and explicit manifest; technical failure is never mapped to unreadable |
| AC-16 | Dashboard alone resolves every review mode; at least one real AI-assisted cloud pipeline and real Telegram handshake are demonstrated |

| AC-17 | Map a participant record with no receipt timestamp to a valid Case with received_at=null; no ingestion block, guessed time, business review, or export exclusion |
| AC-18 | Dashboard renders known and unknown receipt times without invalid dates; created_at/updated_at remain accurately labelled system activity |
| AC-19 | Reprocessing preserves Case.created_at and unknown received_at, advances run.started_at, and emits schema_version=2.1.2 after coordinated adoption; validator rejects an omitted received_at or malformed non-null timestamp |

### Voice extension acceptance gate

AC-20–AC-24 gate activation of PRD 3 real decisions, not completion of the existing Telegram/dashboard MVP while voice is disabled.

| ID | Scenario and expected result |
|---|---|
| AC-20 | Authenticated VOICE action uses the same validator, returns durable 202, persists channel=VOICE and resumes processing without changing machine_assessment |
| AC-21 | Voice races Telegram/dashboard or receives repeated callbacks: one durable acceptance; duplicates/stale submissions do not create new work or apply to a new review |
| AC-22 | Missing/expired identity, spoofed caller ID, invalid provider callback or guessed private object is denied without disclosure or decision |
| AC-23 | Silence, negation, changed value/run and unbound yes do not submit; unsupported value requires exact override confirmation and retains ungrounded provenance |
| AC-24 | Call failure/restart/timeout preserves or reconciles accepted work, leaves unconfirmed reviews pending and retains Telegram fallback; voice does not mutate notified_at |

## 14. Organizer verification and release gates

These are narrow unresolved external facts, not a reason to reopen the architecture.

| Item | Current baseline / action | Owner |
|---|---|---|
| Vocabulary, seven fields, output shape | Confirmed against the inspected participant README/template; validate the implemented adapter against the pinned source in B0 | B |
| NOT_READY/no-attachment intention | Diagnostic only; no scored bypass. Obtain permitted evaluator or organizer clarification before changing behavior | A/B |
| Readable ambiguity/semantic uncertainty reason | Provisional unreadable when located but uninterpretable; missing_value when absent; semantic AI off scored path | A/B |
| Text unit, numeric tolerance, blanks | Use conservative policies in PRD 1; record any organizer-confirmed amendment with tests and config version | A |
| Dataset sharing and external AI permissions | Public/bot use synthetic or explicitly approved data only; confirm permitted private processing before sending organizer content to external providers | B/C |
| Evaluator metric names/usage terms | Preserve actual endpoint fields in validation report; confirm participant-facing interface, never inspect private answer keys | B |

The inspected participant ZIP contains 520 emails (126 with attachments) and 250 attachment files: 192 TXT, 28 PDF, 8 DOCX, and 22 XLSX. All 520 emails lack received_at. Recompute the required ID set and inventory when the input version changes. sample_submission.json is a shape template, not ground truth; its GENERAL placeholders must not become classification labels.

The official problem statement treats text-based classification/extraction/comparison as the baseline and richer formats as advanced work. Our broader format coverage is a project commitment driven by the provided files. The self-evaluation endpoint is optional and not the final assessment; complete exports and reproducible snapshots remain our internal validation/release requirements when using that interface.

Synthetic fixtures can establish F0/F1 interaction behavior, but cannot establish classification or extraction accuracy on participant data. Consult representative source structures while designing fixtures, keep public fixtures synthetic/demo-safe, and perform real-data validation privately during backend integration.

## 15. v2.1 change summary

Merged nullable classification, UNKNOWN roles, per-value provenance, multi-location evidence, review run identity, and supersession into actual types. Added durable decision acceptance and guarded worker writes; operational manual-override comparability and G1–G3 for human/candidate values; bounded sequential reviews; server-enforced demo isolation; fail-closed snapshots; asynchronous API behavior; restart-safe notifications/replies; dependency recomputation; scoped metrics; and explicit acceptance cases.

The PRDs now put minimum grounding and one real AI path in the MUST core, manual confirmation in the first dashboard/Telegram phases, and the first real handshake before accuracy expansion. Natural-language Telegram AI remains SHOULD. Small local PRD modifications remain permitted under this authoritative contract.

### v2.1.1 amendment

Allow unknown source receipt time explicitly; define existing system timestamps; align mapper, frontend, simulator, validators, and acceptance cases; incorporate directly observed participant structure; distinguish optional organizer self-evaluation from project validation commitments. Preserve Hermes as the PRD 2 implementation choice and all existing decision, privacy, and export safeguards.

### v2.1.2 amendment

Add VOICE channel and scoped voice actor assertions; preserve existing business types, actions, grounding, budgets and execution. Define shared routing/confirmation and unchanged Telegram notification semantics. Add coordinated schema migration and optional-extension acceptance gates. PRD 3 owns voice implementation; PRD 2 owns shared interaction integration. Pending team adoption does not block the existing deployed MVP.

## Appendix A. Payload examples

### Complete initial Case returned by a new create request

This is a full valid processing-state synthetic fixture with unknown receipt time, matching the absence observed in participant records. It deliberately has no classification or assessment yet; it is not an example of a completed BL comparison. A separate synthetic known-time variant may set received_at to "2026-09-19T08:00:00Z"; that fictional time is not participant metadata.

~~~json
{
  "schema_version": "2.1.2",
  "case_id": "demo_email_001",
  "run": {
    "run_id": "demo_run_001",
    "kind": "DEMO",
    "started_at": "2026-09-19T09:00:00Z",
    "input_version": "synthetic-input-v1",
    "config_version": "pipeline-v1",
    "demo_safe": true
  },
  "email": {
    "email_id": "demo_email_001",
    "from": "demo@example.com",
    "subject": "Verify draft BL — synthetic fixture",
    "received_at": null,
    "category": null,
    "classified_by": null,
    "classification_reason": null
  },
  "documents": [],
  "workflow_status": "PROCESSING",
  "machine_assessment": null,
  "fields": [],
  "review": null,
  "resolution": null,
  "follow_up": "NONE",
  "failure": null,
  "history": [
    {
      "event_id": "event_001",
      "run_id": "demo_run_001",
      "at": "2026-09-19T09:00:00Z",
      "type": "CASE_CREATED",
      "actor": {
        "kind": "SYSTEM",
        "id": null
      },
      "summary": "Synthetic demo run queued.",
      "details": null
    }
  ],
  "metrics": {
    "ai_calls": 0,
    "ai_assisted_fields": 0,
    "processing_ms": null,
    "est_ai_cost_usd": null
  },
  "created_at": "2026-09-19T09:00:00Z",
  "updated_at": "2026-09-19T09:00:00Z",
  "completed_at": null
}
~~~

### Confirmed manual-override request

This request is valid only for the corresponding active OPEN FIELD/VALUE_INPUT review targeting BL gross_weight_kg, after the actor has explicitly confirmed this exact proposal. The server validates the actor and tuple; the example is not a reusable authorization token.

~~~json
{
  "review_id": "review_001",
  "run_id": "demo_run_001",
  "channel": "TELEGRAM",
  "actor_id": "allowlisted_demo_actor",
  "action": "PROVIDE_VALUE",
  "field": "gross_weight_kg",
  "side": "BL",
  "value": 21707,
  "override_confirmation": {
    "review_id": "review_001",
    "run_id": "demo_run_001",
    "field": "gross_weight_kg",
    "side": "BL",
    "proposed_value": 21707,
    "confirmed": true
  }
}
~~~

The endpoint returns 202 with the complete Case in PROCESSING, the review CLOSED, and durable pending work. After application, the working value has resolved_by=HUMAN, value_origin=MANUAL_OVERRIDE, grounded=false, and the confirmation in override_confirmations. If every other field matches, the operational resolution is OK and workflow COMPLETED; if container_count differs, resolution is MISMATCH with that defect. The original NEEDS_REVIEW machine assessment and its exported empty defect list remain unchanged.
