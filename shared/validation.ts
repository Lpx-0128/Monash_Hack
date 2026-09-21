import { z } from "zod";
import type { Case, CaseSummary, Review, Stats } from "./types";

export const fields = [
  "shipper",
  "consignee",
  "notify_party",
  "port_of_loading",
  "port_of_discharge",
  "container_count",
  "gross_weight_kg",
] as const;
export const categories = [
  "BL_COMPARISON",
  "SI_REQUEST",
  "INVOICE_QUERY",
  "GENERAL",
  "SPAM",
] as const;
export const workflows = [
  "PROCESSING",
  "AWAITING_HUMAN",
  "BLOCKED_EXTERNAL",
  "COMPLETED",
  "FAILED",
] as const;
export const statuses = ["OK", "MISMATCH", "NEEDS_REVIEW"] as const;
const id = z.string().min(1),
  time = z.iso.datetime(),
  count = z.number().int().nonnegative();
const field = z.enum(fields),
  status = z.enum(statuses),
  side = z.enum(["SI", "BL"]);
const reason = z.enum([
  "wrong_doc_type",
  "missing_attachment",
  "unreadable",
  "missing_value",
]);
const actor = z.enum(["DETERMINISTIC", "AI", "HUMAN"]);
const action = z.enum(["SELECT_OPTION", "PROVIDE_VALUE", "ACKNOWLEDGE"]);
const scalar = z.union([
  z.string().trim().min(1),
  z.number().positive().finite(),
]);
const obj = z.strictObject;
export const evidenceSchema = obj({
  document_id: id,
  source_text: id,
  locator: z.discriminatedUnion("kind", [
    obj({ kind: z.literal("text_range"), start: count, end: count }).refine(
      (v) => v.end > v.start,
      "Empty evidence range",
    ),
    obj({ kind: z.literal("pdf_page"), page: z.number().int().positive() }),
    obj({ kind: z.literal("docx_paragraph"), index: count }),
    obj({
      kind: z.literal("docx_table_cell"),
      table: count,
      row: count,
      column: count,
    }),
    obj({
      kind: z.literal("sheet_cell"),
      sheet: id,
      cell: z.string().regex(/^[A-Z]+[1-9][0-9]*$/),
    }),
  ]),
});
const confirmation = obj({
  review_id: id,
  run_id: id,
  field,
  side,
  proposed_value: scalar,
  confirmed: z.literal(true),
});
export const valueSchema = obj({
  raw: z.string().nullable(),
  normalized: scalar.nullable(),
  evidence: z.array(evidenceSchema),
  resolved_by: actor,
  value_origin: z.enum([
    "DOCUMENT_EXTRACTED",
    "DOCUMENT_CONFIRMED",
    "MANUAL_OVERRIDE",
  ]),
  grounded: z.boolean(),
  flags: z.array(z.string()),
  override_confirmations: z.array(confirmation),
}).superRefine((v, c) => {
  const fail = (message: string) => c.addIssue({ code: "custom", message });
  if (v.grounded && (!v.evidence.length || v.normalized === null))
    fail("Grounding requires a value and evidence");
  if (
    v.value_origin === "DOCUMENT_CONFIRMED" &&
    (!v.grounded || v.resolved_by !== "HUMAN")
  )
    fail("Document confirmation must be grounded and human");
  if (
    v.value_origin === "MANUAL_OVERRIDE" &&
    (v.grounded || !v.override_confirmations.length)
  )
    fail("Overrides must remain ungrounded with confirmation lineage");
  if (v.value_origin !== "MANUAL_OVERRIDE" && v.override_confirmations.length)
    fail("Override lineage requires manual override provenance");
});
const optionSchema = z.discriminatedUnion("kind", [
  obj({
    kind: z.literal("DOCUMENT"),
    option_id: id,
    label: id,
    document_id: id,
  }),
  obj({
    kind: z.literal("VALUE"),
    option_id: id,
    label: id,
    value: valueSchema,
  }),
  obj({
    kind: z.literal("ESCAPE"),
    option_id: z.literal("NONE_OF_THESE"),
    label: id,
  }),
]);
export const reviewSchema = obj({
  review_id: id,
  case_id: id,
  run_id: id,
  status: z.enum(["OPEN", "CLOSED"]),
  scope: z.enum(["FIELD", "DOCUMENT"]),
  ui_mode: z.enum(["CHOICE", "VALUE_INPUT", "ACKNOWLEDGE"]),
  reason,
  field: field.nullable(),
  side: side.nullable(),
  target_role: side.nullable(),
  question: id,
  context_summary: id,
  options: z.array(optionSchema).nullable(),
  allowed_actions: z.array(action),
  source_documents: z.array(
    obj({ document_id: id, filename: id, media_type: id }),
  ),
  created_at: time,
  notified_at: time.nullable(),
  closed_at: time.nullable(),
  close_reason: z
    .enum(["DECISION_ACCEPTED", "SUPERSEDED", "TECHNICAL_FAILURE"])
    .nullable(),
}).superRefine((r, c) => {
  const fail = (message: string) => c.addIssue({ code: "custom", message });
  if (
    r.status === "OPEN"
      ? r.closed_at !== null || r.close_reason !== null
      : !r.closed_at || !r.close_reason
  )
    fail("Review closure metadata disagrees with status");
  if (
    r.scope === "FIELD"
      ? !r.field ||
        !r.side ||
        r.target_role !== null ||
        r.ui_mode === "ACKNOWLEDGE"
      : r.field !== null ||
        r.side !== null ||
        (r.ui_mode === "CHOICE" ? !r.target_role : r.target_role !== null)
  )
    fail("Invalid review target");
  if (r.scope === "DOCUMENT" && r.ui_mode === "VALUE_INPUT")
    fail("Document reviews cannot request a field value");
  const expected =
    r.ui_mode === "CHOICE"
      ? ["SELECT_OPTION"]
      : r.ui_mode === "VALUE_INPUT"
        ? ["ACKNOWLEDGE", "PROVIDE_VALUE"]
        : ["ACKNOWLEDGE"];
  if ([...r.allowed_actions].sort().join() !== expected.sort().join())
    fail("Allowed actions disagree with mode");
  if (r.ui_mode === "CHOICE") {
    const opts = r.options ?? [];
    if (
      new Set(opts.map((o) => o.option_id)).size !== opts.length ||
      opts.filter((o) => o.option_id === "NONE_OF_THESE" && o.kind === "ESCAPE")
        .length !== 1
    )
      fail("Choice requires unique options and one NONE_OF_THESE");
    const candidates = opts.filter((o) => o.kind !== "ESCAPE");
    if (
      candidates.length < (r.scope === "FIELD" ? 2 : 1) ||
      candidates.some(
        (o) => o.kind !== (r.scope === "FIELD" ? "VALUE" : "DOCUMENT"),
      )
    )
      fail("Choice candidates disagree with scope");
  } else if (r.options !== null) fail("Non-choice review options must be null");
});
const assessment = obj({
  status,
  review_reason: reason.nullable(),
  has_defect: z.boolean(),
  defect_fields: z.array(field),
  assessed_at: time,
}).superRefine((a, c) => {
  if (
    new Set(a.defect_fields).size !== a.defect_fields.length ||
    (a.status === "MISMATCH"
      ? !a.has_defect || !a.defect_fields.length || a.review_reason !== null
      : a.has_defect ||
        a.defect_fields.length > 0 ||
        (a.status === "NEEDS_REVIEW"
          ? a.review_reason === null
          : a.review_reason !== null))
  )
    c.addIssue({
      code: "custom",
      message: "Invalid machine assessment roll-up",
    });
});
const comparison = obj({
  field,
  si: valueSchema.nullable(),
  bl: valueSchema.nullable(),
  result: z.enum(["MATCH", "MISMATCH", "NOT_COMPARABLE"]),
  not_comparable_cause: z
    .enum([
      "MISSING_VALUE",
      "UNREADABLE",
      "AMBIGUOUS",
      "UNGROUNDED",
      "INVALID_VALUE",
      "SEMANTIC_UNCERTAIN",
      "DOCUMENT_LEVEL",
    ])
    .nullable(),
  compared_by: actor,
}).superRefine((f, c) => {
  const fail = (message: string) => c.addIssue({ code: "custom", message });
  if ((f.result === "NOT_COMPARABLE") !== (f.not_comparable_cause !== null))
    fail("Comparison cause must match NOT_COMPARABLE");
  for (const v of [f.si, f.bl])
    if (v?.normalized != null) {
      const numeric =
        f.field === "container_count" || f.field === "gross_weight_kg";
      if (
        numeric
          ? typeof v.normalized !== "number"
          : typeof v.normalized !== "string"
      )
        fail("Canonical field has incorrect value type");
      if (f.field === "container_count" && !Number.isSafeInteger(v.normalized))
        fail("Count must be a positive safe integer");
    }
  if (f.result !== "NOT_COMPARABLE") {
    if (
      [f.si, f.bl].some(
        (v) =>
          !v ||
          v.normalized === null ||
          (!v.grounded && v.value_origin !== "MANUAL_OVERRIDE"),
      )
    )
      fail("Comparable values require grounding or explicit override");
    if (
      f.si &&
      f.bl &&
      (f.si.normalized === f.bl.normalized) !== (f.result === "MATCH")
    )
      fail("Comparison must follow canonical exact equality");
  }
});
const historyType = z.enum([
  "CASE_CREATED",
  "EMAIL_CLASSIFIED",
  "DOCUMENT_PARSED",
  "AI_EXTRACTION_USED",
  "COMPARISON_COMPLETED",
  "MISMATCH_VERIFIED",
  "REVIEW_CREATED",
  "REVIEW_NOTIFIED",
  "DECISION_RECEIVED",
  "DECISION_APPLIED",
  "DECISION_REJECTED",
  "RETRY_TRIGGERED",
  "PROCESSING_FAILED",
  "REVIEW_SUPERSEDED",
  "CASE_REPROCESSED",
  "CASE_COMPLETED",
]);
export const caseSchema: z.ZodType<Case> = obj({
  schema_version: z.union([z.literal("2.1.1"), z.literal("2.1.2")]),
  case_id: id,
  run: obj({
    run_id: id,
    kind: z.enum(["EVAL", "DEMO"]),
    started_at: time,
    input_version: id,
    config_version: id,
    demo_safe: z.boolean(),
  }),
  email: obj({
    email_id: id,
    from: id,
    subject: id,
    received_at: time.nullable(),
    category: z.enum(categories).nullable(),
    classified_by: z.enum(["DETERMINISTIC", "AI"]).nullable(),
    classification_reason: z.string().nullable(),
  }),
  documents: z.array(
    obj({
      document_id: id,
      role: z.enum(["UNKNOWN", "SI", "BL", "OTHER"]),
      filename: id,
      media_type: id,
      size_bytes: count.nullable(),
      content_hash: id,
      demo_safe: z.boolean(),
      parse_status: z.enum(["OK", "UNREADABLE", "UNSUPPORTED", "NOT_PARSED"]),
    }),
  ),
  workflow_status: z.enum(workflows),
  machine_assessment: assessment.nullable(),
  fields: z.array(comparison),
  review: reviewSchema.nullable(),
  resolution: obj({
    review_id: id,
    run_id: id,
    action,
    value_source: z.enum(["DOCUMENT_CONFIRMED", "MANUAL_OVERRIDE"]).nullable(),
    actor_id: id,
    channel: z.enum(["TELEGRAM", "DASHBOARD", "VOICE"]),
    user_message: z.string().nullable(),
    resolved_at: time,
    final_status: status,
    final_defect_fields: z.array(field),
  }).nullable(),
  follow_up: z.enum(["NONE", "CORRECTION_REQUIRED", "AWAIT_EXTERNAL"]),
  failure: obj({ step: id, message: id, attempts: count }).nullable(),
  history: z.array(
    obj({
      event_id: id,
      run_id: id,
      at: time,
      type: historyType,
      actor: obj({
        kind: z.enum(["SYSTEM", "AI", "HUMAN"]),
        id: id.nullable(),
      }),
      summary: id,
      details: z.record(z.string(), z.unknown()).nullable(),
    }),
  ),
  metrics: obj({
    ai_calls: count,
    ai_assisted_fields: count.max(14),
    processing_ms: z.number().nonnegative().nullable(),
    est_ai_cost_usd: z.number().nonnegative().nullable(),
  }),
  created_at: time,
  updated_at: time,
  completed_at: time.nullable(),
}).superRefine((v, c) => {
  const fail = (message: string) => c.addIssue({ code: "custom", message });
  const w = v.workflow_status,
    a = v.machine_assessment,
    r = v.review,
    effective = v.resolution?.final_status ?? a?.status ?? null;
  if (!a && !["PROCESSING", "FAILED"].includes(w))
    fail("Settled state requires assessment");
  if (a && (!v.email.category || !v.email.classified_by))
    fail("Assessment requires classification");
  if (
    w === "AWAITING_HUMAN" &&
    (!r || r.status !== "OPEN" || r.ui_mode === "ACKNOWLEDGE")
  )
    fail("Awaiting human requires open actionable review");
  if (
    w === "BLOCKED_EXTERNAL" &&
    (!r || (r.status === "OPEN" && r.ui_mode !== "ACKNOWLEDGE"))
  )
    fail("External block requires acknowledgment or closed escape review");
  if (
    w === "COMPLETED" &&
    (r?.status === "OPEN" || !effective || effective === "NEEDS_REVIEW")
  )
    fail("Completed requires settled outcome without open review");
  if (w === "FAILED" && (!v.failure || r?.status === "OPEN"))
    fail("Failure must have diagnostics and no open review");
  if (w !== "FAILED" && v.failure !== null)
    fail("Failure metadata belongs to FAILED");
  if (r && (r.run_id !== v.run.run_id || r.case_id !== v.case_id))
    fail("Current review must belong to active case and run");
  if (
    r?.status === "OPEN" &&
    !["AWAITING_HUMAN", "BLOCKED_EXTERNAL"].includes(w)
  )
    fail("Open reviews require a waiting workflow");
  if (v.resolution && v.resolution.run_id !== v.run.run_id)
    fail("Resolution must belong to active run");
  if (
    v.resolution &&
    (v.resolution.final_status === "MISMATCH"
      ? !v.resolution.final_defect_fields.length
      : v.resolution.final_defect_fields.length > 0)
  )
    fail("Invalid operational defects");
  if (new Set(v.fields.map((f) => f.field)).size !== v.fields.length)
    fail("Duplicate canonical field");
  if (
    v.email.category === "BL_COMPARISON" &&
    !["PROCESSING", "FAILED"].includes(w) &&
    v.fields.length !== 7
  )
    fail("Settled BL case requires seven fields");
  if (
    v.email.category &&
    v.email.category !== "BL_COMPARISON" &&
    (v.fields.length || a?.status !== "OK")
  )
    fail("Non-BL must have OK assessment and no comparisons");
  if ((w === "COMPLETED") !== (v.completed_at !== null))
    fail("Completion timestamp iff operationally complete");
  const follow =
    w === "BLOCKED_EXTERNAL"
      ? "AWAIT_EXTERNAL"
      : effective === "MISMATCH"
        ? "CORRECTION_REQUIRED"
        : "NONE";
  if (v.follow_up !== follow) fail("Incorrect follow-up derivation");
  const docs = new Set(v.documents.map((d) => d.document_id));
  if (docs.size !== v.documents.length) fail("Duplicate document ID");
  for (const role of ["SI", "BL"])
    if (v.documents.filter((d) => d.role === role).length > 1)
      fail("More than one assigned document per role");
  const values = v.fields
    .flatMap((f) => [f.si, f.bl])
    .concat(
      r?.options?.flatMap((o) => (o.kind === "VALUE" ? [o.value] : [])) ?? [],
    );
  if (
    values.some((value) =>
      value?.evidence.some((e) => !docs.has(e.document_id)),
    )
  )
    fail("Evidence references unknown document");
  if (
    r?.source_documents.some((d) => !docs.has(d.document_id)) ||
    r?.options?.some((o) => o.kind === "DOCUMENT" && !docs.has(o.document_id))
  )
    fail("Review references unknown document");
  for (const f of v.fields)
    for (const [sideName, value] of [
      ["SI", f.si],
      ["BL", f.bl],
    ] as const) {
      if (
        value?.value_origin === "MANUAL_OVERRIDE" &&
        value.resolved_by === "HUMAN" &&
        !value.override_confirmations.some(
          (o) =>
            o.run_id === v.run.run_id &&
            o.field === f.field &&
            o.side === sideName &&
            o.proposed_value === value.normalized,
        )
      )
        fail(
          "Direct human override requires confirmation bound to run, field, side and canonical value",
        );
    }
  if (w === "COMPLETED") {
    const expected = v.fields.some((f) => f.result === "NOT_COMPARABLE")
      ? "NEEDS_REVIEW"
      : v.fields.some((f) => f.result === "MISMATCH")
        ? "MISMATCH"
        : "OK";
    if (effective !== expected)
      fail("Operational outcome disagrees with fields");
  }
});
export const summarySchema: z.ZodType<CaseSummary> = obj({
  case_id: id,
  run_id: id,
  from: id,
  subject: id,
  category: z.enum(categories).nullable(),
  workflow_status: z.enum(workflows),
  machine_status: status.nullable(),
  review_reason: reason.nullable(),
  final_status: status.nullable(),
  mismatch_count: count.max(7),
  has_open_review: z.boolean(),
  run_kind: z.enum(["EVAL", "DEMO"]),
  updated_at: time,
});
export const statsSchema: z.ZodType<Stats> = obj({
  generated_at: time,
  run_kind: z.enum(["EVAL", "DEMO"]),
  total_cases: count,
  unclassified: count,
  by_category: z.record(z.enum(categories), count),
  bl_comparison: obj({
    total: count,
    ok: count,
    mismatch: count,
    needs_review: count,
  }),
  by_machine_status: z.record(status, count),
  by_effective_status: z.record(status, count),
  by_workflow: z.record(z.enum(workflows), count),
  awaiting_human_now: count,
  auto_completed: count,
  ai_assisted_cases: count,
  ai_calls_total: count,
  avg_processing_ms: z.number().nonnegative().nullable(),
}).superRefine((s, c) => {
  if (
    Object.values(s.by_workflow).reduce((a, b) => a + b, 0) !== s.total_cases ||
    Object.values(s.by_category).reduce((a, b) => a + b, 0) + s.unclassified !==
      s.total_cases ||
    Object.values(s.by_machine_status).reduce((a, b) => a + b, 0) >
      s.total_cases ||
    Object.values(s.by_effective_status).reduce((a, b) => a + b, 0) >
      s.total_cases ||
    s.bl_comparison.ok +
      s.bl_comparison.mismatch +
      s.bl_comparison.needs_review !==
      s.bl_comparison.total ||
    s.auto_completed > s.by_workflow.COMPLETED ||
    s.awaiting_human_now >
      s.by_workflow.AWAITING_HUMAN + s.by_workflow.BLOCKED_EXTERNAL ||
    s.ai_assisted_cases > s.total_cases
  )
    c.addIssue({
      code: "custom",
      message: "Statistics violate count invariants",
    });
});
export const reviewListSchema = z.array(
  obj({ review: reviewSchema, case: summarySchema }),
);
export const errorSchema = obj({
  error: obj({
    code: z.enum([
      "REVIEW_ALREADY_CLOSED",
      "STALE_RUN",
      "ACTION_NOT_ALLOWED",
      "INVALID_VALUE",
      "VALUE_NOT_FOUND_IN_DOCUMENT",
      "OVERRIDE_CONFIRMATION_REQUIRED",
      "INVALID_CONFIRMATION",
      "OPTION_NOT_FOUND",
      "NOT_FOUND",
      "UNAUTHORIZED",
      "FORBIDDEN",
      "RATE_LIMITED",
      "INTERNAL",
    ]),
    message: id,
    current_case: caseSchema.optional(),
  }),
});
export const validateCase = (value: unknown): Case => caseSchema.parse(value);
export const effectiveStatus = (c: Case) =>
  c.resolution?.final_status ?? c.machine_assessment?.status ?? null;
export function assertDemo(c: Case) {
  if (
    c.run.kind !== "DEMO" ||
    !c.run.demo_safe ||
    c.documents.some((d) => !d.demo_safe)
  )
    throw new Error("Case is outside demo-safe scope");
}

export const gmailStatusSchema = obj({
  configured: z.boolean(),
  connected: z.boolean(),
  folder: z.string().nullable(),
  unseen_count: z.number().int().nonnegative().nullable(),
  error: z.string().nullable(),
});

export const gmailSyncResponseSchema = obj({
  status: z.enum(["OK", "ERROR"]),
  fetched: z.number().int().nonnegative(),
  created_cases: z.array(z.string()),
  error: z.string().nullable().optional(),
});

export const gmailClearResponseSchema = z.object({
  status: z.string(),
  deleted_count: z.number().int().nonnegative(),
  message: z.string().nullable().optional(),
}).passthrough();


