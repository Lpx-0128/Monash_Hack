import { randomUUID, createHash } from "node:crypto";
import type {
  Case,
  Review,
  DecisionRequest,
  FieldValue,
  CanonicalField,
  Side,
} from "../shared/types";
import { decisionSchema, parseProposal } from "../shared/decisions";
import { fields, validateCase } from "../shared/validation";
import {
  canonicalSyntheticValue,
  supportsSyntheticField,
} from "./synthetic-layout";
import { auditDocuments, history, labels } from "./fixtures";
import { ApiError } from "./errors";
export interface AcceptedWork {
  decision: DecisionRequest;
  review: Review;
  value: FieldValue | null;
  documentId: string | null;
  escape: boolean;
  status: "pending" | "applied" | "failed" | "superseded";
  fail: boolean;
}
const reject = (code: string, message: string): never => {
  throw new ApiError(422, code, message);
};
/** Deliberately bounded synthetic layout parser; no AI or participant extraction. */
export function sourceValues(
  c: Case,
  documents: Map<string, string>,
  side: Side,
  field: CanonicalField,
  assignedId?: string,
): FieldValue[] {
  const doc = c.documents.find((d) =>
    assignedId ? d.document_id === assignedId : d.role === side,
  );
  if (!doc) return [];
  const text = documents.get(doc.document_id);
  if (
    text === undefined ||
    createHash("sha256").update(text).digest("hex") !== doc.content_hash
  )
    throw new Error("Immutable synthetic source changed");
  const values: FieldValue[] = [];
  const lines = text.split("\n");
  let position = 0;
  for (let i = 0; i < lines.length; i++) {
    let quote = lines[i],
      consumed = quote.length + 1;
    while (i + 1 < lines.length && /^  \S/.test(lines[i + 1])) {
      quote += "\n" + lines[++i];
      consumed += lines[i].length + 1;
    }
    const colon = quote.indexOf(":");
    if (colon >= 0) {
      const raw = quote.slice(colon + 1).trim();
      if (raw === "[not supplied]") {
        position += consumed;
        continue;
      }
      let normalized: string | number | null = null;
      try {
        normalized = canonicalSyntheticValue(field, raw);
      } catch {
        /* Different field or explicit missing value. */
      }
      if (
        normalized !== null &&
        supportsSyntheticField(quote, field, normalized)
      )
        values.push({
          raw,
          normalized,
          evidence: [
            {
              document_id: doc.document_id,
              source_text: quote,
              locator: {
                kind: "text_range",
                start: Array.from(text.slice(0, position)).length,
                end: Array.from(text.slice(0, position) + quote).length,
              },
            },
          ],
          resolved_by: "DETERMINISTIC",
          value_origin: "DOCUMENT_EXTRACTED",
          grounded: true,
          flags: [],
          override_confirmations: [],
        });
    }
    position += consumed;
  }
  return values;
}
export function prepareDecision(
  c: Case,
  r: Review,
  pathId: string,
  input: unknown,
  actor: string,
  documents: Map<string, string>,
): AcceptedWork {
  const parsed = decisionSchema.safeParse(input);
  if (!parsed.success)
    reject(
      parsed.error.issues.some((i) => i.path[0] === "override_confirmation")
        ? "INVALID_CONFIRMATION"
        : "INVALID_VALUE",
      "Invalid decision shape. Only contract decision fields are accepted.",
    );
  const d = parsed.data!;
  if (d.actor_id !== actor || d.channel !== "DASHBOARD")
    throw new ApiError(
      403,
      "FORBIDDEN",
      "Decision actor and channel must match this authenticated demo session.",
    );
  if (d.review_id !== pathId)
    reject("INVALID_VALUE", "Path and body review IDs differ.");
  if (r.status !== "OPEN")
    throw new ApiError(
      409,
      "REVIEW_ALREADY_CLOSED",
      "This review has already been handled or superseded. Refresh the case.",
    );
  if (d.run_id !== r.run_id || c.run.run_id !== d.run_id)
    throw new ApiError(
      409,
      "STALE_RUN",
      "The review belongs to a different run. Refresh the case.",
    );
  if (!r.allowed_actions.includes(d.action))
    reject(
      "ACTION_NOT_ALLOWED",
      "This action is not permitted by the current review.",
    );
  const work: AcceptedWork = {
    decision: d,
    review: structuredClone(r),
    value: null,
    documentId: null,
    escape: d.action === "ACKNOWLEDGE",
    status: "pending",
    fail: c.case_id === "demo_resume-failure",
  };
  let proposed: string | number | null = null;
  let raw: string | null = null;
  if (d.action === "PROVIDE_VALUE") {
    if (r.scope !== "FIELD" || d.field !== r.field || d.side !== r.side)
      reject(
        "ACTION_NOT_ALLOWED",
        "Field and side must match the current review.",
      );
    try {
      proposed = parseProposal(d.field, d.value);
    } catch (e) {
      reject("INVALID_VALUE", (e as Error).message);
    }
    raw = String(d.value);
    d.value = proposed!;
  } else if (d.action === "SELECT_OPTION") {
    const option = r.options?.find((o) => o.option_id === d.option_id);
    if (!option)
      reject(
        "OPTION_NOT_FOUND",
        "Option is not a member of the current review.",
      );
    if (option!.kind === "ESCAPE") work.escape = true;
    else if (option!.kind === "DOCUMENT") {
      if (r.scope !== "DOCUMENT" || !r.target_role)
        reject("ACTION_NOT_ALLOWED", "No document role is targeted.");
      const doc = c.documents.find(
        (v) => v.document_id === option!.document_id,
      );
      if (!doc || (doc.role !== "UNKNOWN" && doc.role !== r.target_role))
        reject(
          "ACTION_NOT_ALLOWED",
          "A document cannot occupy both SI and BL roles.",
        );
      work.documentId = doc!.document_id;
    } else if (option!.kind === "VALUE") {
      if (!r.field || !r.side) reject("ACTION_NOT_ALLOWED", "No field target.");
      try {
        proposed = parseProposal(r.field!, option!.value.normalized!);
      } catch (e) {
        reject("INVALID_VALUE", (e as Error).message);
      }
      raw = option!.value.raw;
    }
  }
  const conf = d.action !== "ACKNOWLEDGE" ? d.override_confirmation : undefined;
  if (
    conf &&
    (proposed === null ||
      conf.review_id !== r.review_id ||
      conf.run_id !== r.run_id ||
      conf.field !== r.field ||
      conf.side !== r.side ||
      conf.proposed_value !== proposed)
  )
    reject(
      "INVALID_CONFIRMATION",
      "Override confirmation does not match this exact review, run, field, side and canonical value.",
    );
  if (proposed !== null) {
    const grounded = sourceValues(c, documents, r.side!, r.field!).find(
      (v) => v.normalized === proposed,
    );
    if (grounded && !conf)
      work.value = {
        ...grounded,
        resolved_by: "HUMAN",
        value_origin: "DOCUMENT_CONFIRMED",
      };
    else if (!conf)
      reject(
        "VALUE_NOT_FOUND_IN_DOCUMENT",
        "This proposed value cannot be verified against the targeted synthetic source. The review remains open. An exact manual override confirmation is required.",
      );
    else
      work.value = {
        raw,
        normalized: proposed,
        evidence: [],
        resolved_by: "HUMAN",
        value_origin: "MANUAL_OVERRIDE",
        grounded: false,
        flags: ["Human-provided; unsupported by source"],
        override_confirmations: [conf],
      };
  }
  return work;
}
function nextReview(c: Case, previous: Review, now: string): Review | null {
  const unresolved = c.fields.filter((f) => f.result === "NOT_COMPARABLE");
  if (!unresolved.length) return null;
  const accepted = c.history
    .filter((h) => h.run_id === c.run.run_id && h.type === "DECISION_RECEIVED")
    .flatMap((h) => {
      const review = h.details?.review as Review | undefined;
      return review?.scope === "FIELD" && review.field && review.side
        ? [{ field: review.field, side: review.side }]
        : [];
    });
  const touched = new Set(accepted.map((d) => d.field));
  unresolved.forEach((f) => touched.add(f.field));
  const f = fields
    .map((name) => unresolved.find((f) => f.field === name))
    .find(Boolean)!;
  const side: Side =
    !f.si || (!f.si.grounded && f.si.value_origin !== "MANUAL_OVERRIDE")
      ? "SI"
      : "BL";
  const exhausted = accepted.some(
    (d) => d.field === f.field && d.side === side,
  );
  const block =
    touched.size > 2 ||
    exhausted ||
    unresolved.some((f) => f.not_comparable_cause === "DOCUMENT_LEVEL");
  return {
    ...previous,
    review_id: `${c.run.run_id}_review_${randomUUID()}`,
    status: "OPEN",
    closed_at: null,
    close_reason: null,
    created_at: now,
    notified_at: null,
    scope: block ? "DOCUMENT" : "FIELD",
    ui_mode: block ? "ACKNOWLEDGE" : "VALUE_INPUT",
    field: block ? null : f.field,
    side: block ? null : side,
    target_role: null,
    reason: block
      ? "unreadable"
      : f.not_comparable_cause === "MISSING_VALUE"
        ? "missing_value"
        : "unreadable",
    question: block
      ? "Obtain a corrected external source; the bounded review budget is exhausted."
      : `Confirm the ${side} ${labels[f.field]}.`,
    context_summary: `Synthetic recomputation. ${c.fields.some((f) => f.result === "MISMATCH") ? "A known mismatch remains visible." : "Earlier decisions remain applied."}`,
    options: null,
    allowed_actions: block ? ["ACKNOWLEDGE"] : ["PROVIDE_VALUE", "ACKNOWLEDGE"],
  };
}
export function applyDecision(
  current: Case,
  work: AcceptedWork,
  documents: Map<string, string>,
  now: string,
): Case {
  const c = structuredClone(current),
    r = work.review,
    d = work.decision;
  if (c.run.run_id !== d.run_id) throw new Error("Stale work cannot commit");
  if (work.fail) {
    c.workflow_status = "FAILED";
    c.failure = {
      step: "resume-comparison",
      message:
        "Simulated resumption failed after one retry. Accepted decision retained for operator recovery; do not resubmit.",
      attempts: 2,
    };
    c.updated_at = now;
    history(c, "PROCESSING_FAILED", c.failure.message, now, { decision: d });
    return validateCase(c);
  }
  if (work.value)
    c.fields.find((f) => f.field === r.field)![r.side === "SI" ? "si" : "bl"] =
      structuredClone(work.value);
  if (work.documentId) {
    for (const doc of c.documents) {
      if (doc.role === r.target_role) doc.role = "UNKNOWN";
      if (doc.document_id === work.documentId) doc.role = r.target_role!;
    }
    for (const f of c.fields) {
      const values = sourceValues(
        c,
        documents,
        r.target_role!,
        f.field,
        work.documentId,
      );
      f[r.target_role === "SI" ? "si" : "bl"] =
        values.length === 1 ? values[0] : null;
    }
  }
  for (const f of c.fields) {
    const comparable = (v: FieldValue | null) =>
      v &&
      v.normalized !== null &&
      (v.grounded || v.value_origin === "MANUAL_OVERRIDE");
    if (comparable(f.si) && comparable(f.bl)) {
      f.result = f.si!.normalized === f.bl!.normalized ? "MATCH" : "MISMATCH";
      f.not_comparable_cause = null;
    } else {
      f.result = "NOT_COMPARABLE";
      f.not_comparable_cause = f.not_comparable_cause ?? "MISSING_VALUE";
    }
    f.compared_by = "DETERMINISTIC";
  }
  const next = work.escape ? null : nextReview(c, r, now);
  const final =
    work.escape || next
      ? "NEEDS_REVIEW"
      : c.fields.some((f) => f.result === "MISMATCH")
        ? "MISMATCH"
        : "OK";
  c.resolution = {
    review_id: r.review_id,
    run_id: r.run_id,
    action: d.action,
    value_source: work.value
      ? work.value.value_origin === "MANUAL_OVERRIDE"
        ? "MANUAL_OVERRIDE"
        : "DOCUMENT_CONFIRMED"
      : null,
    actor_id: d.actor_id,
    channel: d.channel,
    user_message: d.user_message ?? null,
    resolved_at: now,
    final_status: final,
    final_defect_fields:
      final === "MISMATCH"
        ? c.fields.filter((f) => f.result === "MISMATCH").map((f) => f.field)
        : [],
  };
  c.workflow_status = work.escape
    ? "BLOCKED_EXTERNAL"
    : next
      ? next.ui_mode === "ACKNOWLEDGE"
        ? "BLOCKED_EXTERNAL"
        : "AWAITING_HUMAN"
      : "COMPLETED";
  c.updated_at = now;
  c.completed_at = c.workflow_status === "COMPLETED" ? now : null;
  c.follow_up =
    c.workflow_status === "BLOCKED_EXTERNAL"
      ? "AWAIT_EXTERNAL"
      : final === "MISMATCH"
        ? "CORRECTION_REQUIRED"
        : "NONE";
  history(
    c,
    "DECISION_APPLIED",
    "Accepted human action applied by the synthetic worker.",
    now,
    { decision: d, review: structuredClone(c.review), value: work.value },
  );
  c.history[c.history.length - 1].actor.id = d.actor_id;
  if (next) {
    c.review = next;
    history(c, "REVIEW_CREATED", next.question, now, { review: next });
  }
  if (c.workflow_status === "COMPLETED")
    history(
      c,
      "CASE_COMPLETED",
      "Operational verification settled; the frozen machine assessment is unchanged.",
      now,
    );
  auditDocuments(c, documents);
  return validateCase(c);
}
