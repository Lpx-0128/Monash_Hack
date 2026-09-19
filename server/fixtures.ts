import { createHash } from "node:crypto";
import type {
  Case,
  CanonicalField,
  FieldValue,
  HistoryEventType,
  Review,
  Side,
} from "../shared/types";
import { fields, validateCase } from "../shared/validation";
import {
  alternateWeightQuote,
  canonicalSyntheticValue,
  documentLabels,
  formatSyntheticValue,
  supportsSyntheticField,
  syntheticSourceEmail,
  syntheticValues,
} from "./synthetic-layout";

export const baselineTime = "2026-09-19T09:00:00.000Z";
export const labels: Record<CanonicalField, string> = {
  shipper: "Shipper",
  consignee: "Consignee",
  notify_party: "Notify party",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
  container_count: "Container count",
  gross_weight_kg: "Gross weight (kg)",
};
export const scenarios = [
  ["grounded-input", "Source available · enter BL gross weight"],
  ["both-sides", "Two sides · SI before BL"],
  ["mismatch-review", "Known container mismatch · weight review"],
  ["unsupported-candidate", "Unsupported candidate · explicit override"],
  ["resume-failure", "Decision journey · simulated resumption failure"],
  ["processing", "New booking · awaiting classification"],
  ["match", "Port Klang → Singapore · verified"],
  ["mismatch", "Container quantity differs"],
  ["non-bl", "Invoice enquiry · September freight"],
  ["field-input", "Gross weight needs confirmation"],
  ["candidate-choice", "Two gross-weight candidates"],
  ["document-choice", "Identify the draft bill of lading"],
  ["blocked-open", "Missing draft BL · external action"],
  ["blocked-acknowledged", "Missing draft BL · acknowledged"],
  ["human-resolved", "Gross weight · manual override applied"],
  ["document-confirmed", "Gross weight · source confirmed"],
  ["sequential-first", "Two uncertainties · first review"],
  ["sequential-second", "Two uncertainties · second review"],
  ["failed-before", "Parser unavailable · no assessment"],
  ["failed-after", "Accepted decision · resumption failed"],
  ["accepted-processing", "Accepted decision · processing"],
  ["superseded", "Replayed case · old review superseded"],
  [
    "no-attachment-intent",
    "Draft requested · no attachments · intent unresolved",
  ],
] as const;
export type Scenario = (typeof scenarios)[number][0];
export type DocumentStore = Map<string, string>;
export function history(
  c: Case,
  type: HistoryEventType,
  summary: string,
  at = baselineTime,
  details: Record<string, unknown> | null = null,
) {
  c.history.push({
    event_id: `${c.run.run_id}_event_${c.history.length + 1}`,
    run_id: c.run.run_id,
    at,
    type,
    actor: {
      kind: type.startsWith("DECISION") ? "HUMAN" : "SYSTEM",
      id: type.startsWith("DECISION") ? "synthetic-operator" : null,
    },
    summary,
    details,
  });
}
export function sourceContext(c: Case, scenario: string) {
  return {
    source_email: syntheticSourceEmail(
      c.case_id,
      c.email.subject,
      c.documents.map((d) => `attachments/${d.filename}`),
      scenario === "no-attachment-intent",
    ),
    receipt_timestamp_provenance:
      c.email.received_at === null
        ? "SOURCE_ABSENT"
        : "INDEPENDENTLY_AUTHORED_FICTIONAL_FIXTURE",
    participant_mapping: "MISSING_RECEIPT_MAPS_TO_NULL",
    ...(scenario === "no-attachment-intent"
      ? {
          intent_mapping: "UNRESOLVED",
          classification_basis:
            "Contract v2.1.1 BL baseline; participant intent mapping is not verified.",
        }
      : {}),
  };
}
function finalizeFixture(c: Case, scenario: string) {
  const created = c.history.find(
    (h) => h.run_id === c.run.run_id && h.type === "CASE_CREATED",
  );
  if (created) created.details = sourceContext(c, scenario);
  return validateCase(c);
}
export function makeFixture(
  scenario: Scenario,
  documents: DocumentStore,
  runId = `demo_${scenario}_run_1`,
): Case {
  const caseId = `demo_${scenario}`;
  const c: Case = {
    schema_version: "2.1.1",
    case_id: caseId,
    run: {
      run_id: runId,
      kind: "DEMO",
      started_at: baselineTime,
      input_version: "synthetic-v1",
      config_version: "f0-simulator-v1",
      demo_safe: true,
    },
    email: {
      email_id: caseId,
      from: "operations@meridian.example",
      subject: scenarios.find((s) => s[0] === scenario)![1],
      received_at: [
        "processing",
        "mismatch",
        "no-attachment-intent",
        "failed-before",
      ].includes(scenario)
        ? null
        : baselineTime,
      category: "BL_COMPARISON",
      classified_by: "DETERMINISTIC",
      classification_reason:
        "Predefined synthetic scenario; no extraction performed.",
    },
    documents: [],
    workflow_status: "COMPLETED",
    machine_assessment: {
      status: "OK",
      review_reason: null,
      has_defect: false,
      defect_fields: [],
      assessed_at: baselineTime,
    },
    fields: [],
    review: null,
    resolution: null,
    follow_up: "NONE",
    failure: null,
    history: [],
    metrics: {
      ai_calls: 0,
      ai_assisted_fields: 0,
      processing_ms: 1200,
      est_ai_cost_usd: null,
    },
    created_at: baselineTime,
    updated_at: baselineTime,
    completed_at: baselineTime,
  };
  history(c, "CASE_CREATED", "Synthetic email loaded into the demonstration.");
  if (["processing", "failed-before", "superseded"].includes(scenario)) {
    c.email.category = null;
    c.email.classified_by = null;
    c.email.classification_reason = null;
    c.machine_assessment = null;
    c.workflow_status = scenario === "failed-before" ? "FAILED" : "PROCESSING";
    c.completed_at = null;
    c.metrics.processing_ms = null;
    if (scenario === "failed-before") {
      c.failure = {
        step: "parse",
        message:
          "Synthetic parser service unavailable. Operator recovery required.",
        attempts: 2,
      };
      history(c, "PROCESSING_FAILED", c.failure.message);
    }
    if (scenario === "superseded") {
      const old = makeFixture("field-input", documents, `${runId}_previous`);
      const prior = {
        ...old.review!,
        case_id: caseId,
        status: "CLOSED" as const,
        close_reason: "SUPERSEDED" as const,
        closed_at: baselineTime,
      };
      c.history.unshift(
        ...old.history.map((h) => ({
          ...h,
          summary: `Previous run: ${h.summary}`,
        })),
      );
      c.documents = old.documents;
      c.history.push({
        event_id: `${runId}_superseded`,
        run_id: prior.run_id,
        at: baselineTime,
        type: "REVIEW_SUPERSEDED",
        actor: { kind: "SYSTEM", id: null },
        summary: "Old review superseded. Replies cannot affect the new run.",
        details: { review: prior },
      });
      history(
        c,
        "CASE_REPROCESSED",
        "New synthetic run is queued; prior review is closed.",
      );
    }
    return finalizeFixture(c, scenario);
  }
  if (scenario === "non-bl") {
    c.email.category = "INVOICE_QUERY";
    history(
      c,
      "EMAIL_CLASSIFIED",
      "Synthetic invoice enquiry; comparison is not applicable.",
    );
    history(c, "CASE_COMPLETED", "Synthetic non-comparison case completed.");
    return finalizeFixture(c, scenario);
  }
  const intentUnresolved = scenario === "no-attachment-intent";
  const absentBL = scenario.startsWith("blocked-") || intentUnresolved;
  const unknownWeight = [
    "field-input",
    "human-resolved",
    "failed-after",
    "accepted-processing", "mismatch-review", "resume-failure",
  ].includes(scenario);
  const sequential = scenario.startsWith("sequential-");
  const sources = new Map<Side, Record<CanonicalField, FieldValue>>();
  for (const side of ["SI", "BL"] as const) {
    if (intentUnresolved || (side === "BL" && absentBL)) continue;
    const docId = `${runId}_${side}`;
    let text = `SYNTHETIC DEMONSTRATION DOCUMENT — not a real shipment\n${side === "SI" ? "SHIPPING INSTRUCTION" : "BILL OF LADING (DRAFT)"}\n========================================\nNumeric convention: comma groups thousands; dot is the decimal separator.\n\n`;
    const data = {} as Record<CanonicalField, FieldValue>;
    for (const field of fields) {
      let v = syntheticValues[field];
      if (
        side === "BL" &&
        ["mismatch", "mismatch-review"].includes(scenario) &&
        field === "container_count"
      )
        v = 4;
      const missing =
        side === "BL" &&
        ((unknownWeight && field === "gross_weight_kg") ||
          (sequential && field === "gross_weight_kg"));
      const raw = missing
        ? "[not supplied]"
        : formatSyntheticValue(field, side, v);
      const line = `${documentLabels[side][field]}: ${raw}`;
      const start = Array.from(text).length;
      text += line + "\n";
      data[field] = {
        raw: missing ? null : raw,
        normalized: missing ? null : canonicalSyntheticValue(field, raw),
        evidence: missing
          ? []
          : [
              {
                document_id: docId,
                source_text: line,
                locator: {
                  kind: "text_range",
                  start,
                  end: start + Array.from(line).length,
                },
              },
            ],
        resolved_by: "DETERMINISTIC",
        value_origin: "DOCUMENT_EXTRACTED",
        grounded: !missing,
        flags: [],
        override_confirmations: [],
      };
    }
    if (side === "BL" && ["candidate-choice", "unsupported-candidate"].includes(scenario))
      text += alternateWeightQuote + "\n";
    text +=
      "\nCommodity: SYNTHETIC PAPERBOARD\nBooking Ref: DEMO-042\nVessel: FICTIONAL VOYAGER\nFreight: PREPAID\n";
    documents.set(docId, text);
    c.documents.push({
      document_id: docId,
      role: scenario === "document-choice" && side === "BL" ? "UNKNOWN" : side,
      filename: `synthetic-${scenario}-${side}.txt`,
      media_type: "text/plain",
      size_bytes: Buffer.byteLength(text),
      content_hash: createHash("sha256").update(text).digest("hex"),
      demo_safe: true,
      parse_status: "OK",
    });
    sources.set(side, data);
  }
  c.fields = fields.map((field) => {
    const si = sources.get("SI")?.[field] ?? null,
      bl = sources.get("BL")?.[field] ?? null;
    const missing = !bl || bl.normalized === null;
    return {
      field,
      si,
      bl,
      result: missing
        ? "NOT_COMPARABLE"
        : si!.normalized === bl.normalized
          ? "MATCH"
          : "MISMATCH",
      not_comparable_cause: missing
        ? absentBL
          ? "DOCUMENT_LEVEL"
          : "MISSING_VALUE"
        : null,
      compared_by: "DETERMINISTIC",
    };
  });
  history(
    c,
    "EMAIL_CLASSIFIED",
    "Predefined synthetic BL comparison. No AI called.",
  );
  if (c.documents.length > 0)
    history(
      c,
      "DOCUMENT_PARSED",
      "Synthetic source text and exact evidence locations loaded.",
    );
  const needsReview = !["match", "mismatch"].includes(scenario);
  if (scenario === "mismatch") {
    c.machine_assessment = {
      status: "MISMATCH",
      review_reason: null,
      has_defect: true,
      defect_fields: ["container_count"],
      assessed_at: baselineTime,
    };
    c.follow_up = "CORRECTION_REQUIRED";
  }
  if (needsReview) {
    const reason = absentBL
      ? "missing_attachment"
      : scenario === "document-choice"
        ? "wrong_doc_type"
        : ["candidate-choice", "unsupported-candidate", "document-confirmed", "grounded-input", "both-sides"].includes(scenario)
          ? "unreadable"
          : "missing_value";
    c.machine_assessment = {
      status: "NEEDS_REVIEW",
      review_reason: reason,
      has_defect: false,
      defect_fields: [],
      assessed_at: baselineTime,
    };
    c.workflow_status = absentBL ? "BLOCKED_EXTERNAL" : "AWAITING_HUMAN";
    c.completed_at = null;
    c.follow_up = absentBL ? "AWAIT_EXTERNAL" : "NONE";
    if (intentUnresolved) {
      c.email.classification_reason =
        "Synthetic contract baseline BL_COMPARISON; no-attachment intent mapping remains unresolved pending participant-facing clarification. No skip or new category is inferred.";
    }
    if (scenario === "document-choice")
      c.fields.forEach((f) => {
        f.bl = null;
        f.result = "NOT_COMPARABLE";
        f.not_comparable_cause = "DOCUMENT_LEVEL";
      });
    if (["candidate-choice", "unsupported-candidate", "document-confirmed", "grounded-input", "both-sides"].includes(scenario)) {
      const f = c.fields[6];
      f.result = "NOT_COMPARABLE";
      f.not_comparable_cause = "AMBIGUOUS";
      f.bl!.grounded = false;
      f.bl!.flags = ["Interpretation requires human review"];
    }
    if (scenario === "both-sides") {
      c.fields[6].si!.grounded = false;
      c.fields[6].si!.flags = ["Synthetic SI interpretation uncertainty"];
    }
    if (sequential) {
      c.fields[5].result = "NOT_COMPARABLE";
      c.fields[5].not_comparable_cause = "AMBIGUOUS";
      c.fields[5].bl!.grounded = false;
      c.fields[5].bl!.flags = ["Synthetic extraction uncertainty"];
    }
    c.review = {
      review_id: `${runId}_review_1`,
      case_id: caseId,
      run_id: runId,
      status: "OPEN",
      scope: absentBL || scenario === "document-choice" ? "DOCUMENT" : "FIELD",
      ui_mode: absentBL
        ? "ACKNOWLEDGE"
        : ["candidate-choice", "unsupported-candidate", "document-choice"].includes(scenario)
          ? "CHOICE"
          : "VALUE_INPUT",
      reason,
      field:
        absentBL || scenario === "document-choice"
          ? null
          : sequential
            ? "container_count"
            : "gross_weight_kg",
      side: absentBL || scenario === "document-choice" ? null : scenario === "both-sides" ? "SI" : "BL",
      target_role: scenario === "document-choice" ? "BL" : null,
      question: intentUnresolved
        ? "Clarify the intended workflow and obtain the required SI and draft BL."
        : absentBL
          ? "Obtain the missing draft BL from the sender."
          : scenario === "document-choice"
            ? "Which document is the draft BL?"
            : sequential
              ? "Confirm the BL container count."
              : `Confirm the ${scenario === "both-sides" ? "SI" : "BL"} gross weight in kg.`,
      context_summary: intentUnresolved
        ? "No-attachment intent is unresolved. The email asks for a future draft; the contract baseline remains BL_COMPARISON / NEEDS_REVIEW with missing_attachment. Do not infer GENERAL from the submission template, introduce NOT_READY as a category, or silently skip comparison. Confirm the intended workflow through coordinated participant-facing clarification."
        : scenario === "mismatch-review" ? "Container count already differs (SI 3, BL 4). Resolve weight uncertainty; correction is still required if this mismatch remains." : "Synthetic grounding only. Inspect the source before deciding. This does not demonstrate real extraction.",
      options: null,
      allowed_actions: absentBL
        ? ["ACKNOWLEDGE"]
        : ["PROVIDE_VALUE", "ACKNOWLEDGE"],
      source_documents: c.documents.map(
        ({ document_id, filename, media_type }) => ({
          document_id,
          filename,
          media_type,
        }),
      ),
      created_at: baselineTime,
      notified_at: null,
      closed_at: null,
      close_reason: null,
    };
    if (c.review.ui_mode === "CHOICE") {
      c.review.allowed_actions = ["SELECT_OPTION"];
      if (scenario === "document-choice")
        c.review.options = c.documents
          .filter((d) => d.role === "UNKNOWN")
          .map((d) => ({
            option_id: "draft-bl",
            kind: "DOCUMENT",
            label: d.filename,
            document_id: d.document_id,
          }));
      else {
        const v = structuredClone(sources.get("BL")!.gross_weight_kg);
        v.grounded = true;
        v.flags = [];
        const doc = c.documents.find((d) => d.role === "BL")!,
          txt = documents.get(doc.document_id)!,
          quote = alternateWeightQuote,
          start = Array.from(txt.slice(0, txt.indexOf(quote))).length;
        c.review.options = [
          {
            option_id: "weight-21707",
            kind: "VALUE",
            label: "21707 kg · original line",
            value: v,
          },
          {
            option_id: "weight-22000",
            kind: "VALUE",
            label: "22000 kg · alternate draft",
            value: {
              ...v,
              raw: "22,000 KG",
              normalized: 22000,
              evidence: [
                {
                  document_id: doc.document_id,
                  source_text: quote,
                  locator: {
                    kind: "text_range",
                    start,
                    end: start + quote.length,
                  },
                },
              ],
            },
          },
        ];
      }
      if (scenario === "unsupported-candidate") {
        const option = c.review.options![1];
        if (option.kind === "VALUE") {
          option.label = "23000 kg · unsupported proposal";
          option.value = { ...option.value, raw:"23000", normalized:23000, grounded:false, evidence:[], flags:["Not supported by synthetic source"] };
        }
      }
      c.review.options!.push({
        option_id: "NONE_OF_THESE",
        kind: "ESCAPE",
        label: "None of these",
      });
    }
    history(
      c,
      "COMPARISON_COMPLETED",
      "Frozen synthetic automated assessment: NEEDS_REVIEW.",
    );
    history(c, "REVIEW_CREATED", c.review.question, baselineTime, {
      review: structuredClone(c.review),
    });
  } else
    history(
      c,
      "COMPARISON_COMPLETED",
      `Frozen synthetic automated assessment: ${c.machine_assessment!.status}.`,
    );
  if (
    [
      "human-resolved",
      "document-confirmed",
      "blocked-acknowledged",
      "sequential-second",
      "failed-after",
      "accepted-processing",
    ].includes(scenario)
  ) {
    const r = c.review!;
    r.status = "CLOSED";
    r.closed_at = baselineTime;
    r.close_reason = "DECISION_ACCEPTED";
    const accepted = {
      review_id: r.review_id,
      run_id: runId,
      channel: "DASHBOARD",
      actor_id: "synthetic-operator",
      action: absentBL ? "ACKNOWLEDGE" : "PROVIDE_VALUE",
      ...(absentBL
        ? {}
        : { field: r.field, side: r.side, value: sequential ? 3 : 21707 }),
      ...(["human-resolved", "failed-after", "accepted-processing"].includes(
        scenario,
      )
        ? {
            override_confirmation: {
              review_id: r.review_id,
              run_id: runId,
              field: "gross_weight_kg",
              side: "BL",
              proposed_value: 21707,
              confirmed: true,
            },
          }
        : {}),
    };
    history(
      c,
      "DECISION_RECEIVED",
      "Stored synthetic accepted decision; no user action was performed in this demo.",
      baselineTime,
      { decision: accepted, review: structuredClone(r) },
    );
    if (["failed-after", "accepted-processing"].includes(scenario)) {
      c.workflow_status = scenario === "failed-after" ? "FAILED" : "PROCESSING";
      if (scenario === "failed-after") {
        c.failure = {
          step: "resume-comparison",
          message:
            "Synthetic resumption failure. Accepted decision retained; operator recovery required.",
          attempts: 2,
        };
        history(c, "PROCESSING_FAILED", c.failure.message);
      }
    } else {
      const source =
        scenario === "human-resolved"
          ? "MANUAL_OVERRIDE"
          : "DOCUMENT_CONFIRMED";
      c.resolution = {
        review_id: r.review_id,
        run_id: runId,
        action: absentBL ? "ACKNOWLEDGE" : "PROVIDE_VALUE",
        value_source: absentBL ? null : source,
        actor_id: "synthetic-operator",
        channel: "DASHBOARD",
        user_message: "Stored synthetic example",
        resolved_at: baselineTime,
        final_status: absentBL || sequential ? "NEEDS_REVIEW" : "OK",
        final_defect_fields: [],
      };
      if (!absentBL) {
        const f = c.fields[sequential ? 5 : 6];
        f.bl = {
          ...f.bl!,
          raw: scenario === "human-resolved" ? "21707" : f.bl!.raw,
          normalized: sequential ? 3 : 21707,
          resolved_by: "HUMAN",
          value_origin: source,
          grounded: source === "DOCUMENT_CONFIRMED",
          flags: [],
          override_confirmations:
            source === "MANUAL_OVERRIDE"
              ? [
                  {
                    review_id: r.review_id,
                    run_id: runId,
                    field: f.field,
                    side: "BL",
                    proposed_value: 21707,
                    confirmed: true,
                  },
                ]
              : [],
        };
        f.result = "MATCH";
        f.not_comparable_cause = null;
        f.compared_by = "HUMAN";
      }
      history(
        c,
        "DECISION_APPLIED",
        absentBL
          ? "Acknowledgment recorded; source is still missing."
          : "Stored synthetic decision applied to operational fields.",
      );
      if (sequential) {
        c.review = {
          ...r,
          review_id: `run_${runId}_review_2`,
          status: "OPEN",
          closed_at: null,
          close_reason: null,
          field: "gross_weight_kg",
          question: "Now confirm BL gross weight in kg.",
        };
        history(c, "REVIEW_CREATED", c.review.question, baselineTime, {
          review: structuredClone(c.review),
        });
      } else if (!absentBL) {
        c.workflow_status = "COMPLETED";
        c.completed_at = baselineTime;
      }
    }
  }
  if (c.workflow_status === "COMPLETED")
    history(c, "CASE_COMPLETED", "Synthetic operational outcome completed.");
  return finalizeFixture(c, scenario);
}

/** Fixture-only grounding audit. Production G1–G3 belongs to the real backend. */
export function auditDocuments(c: Case, documents: DocumentStore) {
  for (const d of c.documents) {
    const text = documents.get(d.document_id);
    if (
      text === undefined ||
      createHash("sha256").update(text).digest("hex") !== d.content_hash ||
      Buffer.byteLength(text) !== d.size_bytes
    )
      throw new Error(`Invalid document bytes: ${d.document_id}`);
  }
  const audit = (v: FieldValue | null, f: CanonicalField) => {
    if (!v) return;
    for (const e of v.evidence) {
      const text = documents.get(e.document_id);
      if (
        text === undefined ||
        e.locator.kind !== "text_range" ||
        Array.from(text).slice(e.locator.start, e.locator.end).join("") !==
          e.source_text
      )
        throw new Error("Evidence does not match source range");
      if (v.grounded && !supportsSyntheticField(e.source_text, f, v.normalized))
        throw new Error("Evidence does not support field/value");
    }
  };
  c.fields.forEach((f) => {
    audit(f.si, f.field);
    audit(f.bl, f.field);
  });
  if (c.review?.field)
    c.review.options?.forEach((o) => {
      if (o.kind === "VALUE") audit(o.value, c.review!.field!);
    });
}
