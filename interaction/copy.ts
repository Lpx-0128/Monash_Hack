import type { Case, CanonicalField } from "../shared/types";
import { effectiveStatus } from "../shared/validation";

export const fieldName = (field: CanonicalField | null) =>
  field
    ? {
        shipper: "shipper",
        consignee: "consignee",
        notify_party: "notify party",
        port_of_loading: "loading port",
        port_of_discharge: "discharge port",
        container_count: "container count",
        gross_weight_kg: "gross weight",
      }[field]
    : "document";
export const targetName = (c: Case) => {
  const r = c.review!;
  return r.scope === "DOCUMENT"
    ? `${r.target_role ?? "required"} document`
    : `${r.side} ${fieldName(r.field)}`;
};
const demo = "Synthetic practice case · checks are simulated";
export function mismatchSummary(c: Case) {
  return c.fields
    .filter((f) => f.result === "MISMATCH")
    .map(
      (f) =>
        `${fieldName(f.field)}: SI ${f.si?.normalized ?? "unknown"}, BL ${f.bl?.normalized ?? "unknown"}`,
    )
    .join("; ");
}
export function reviewCopy(c: Case) {
  const r = c.review!;
  const heading =
    r.ui_mode === "ACKNOWLEDGE"
      ? "This case needs help outside the review"
      : r.ui_mode === "CHOICE"
        ? `Which ${targetName(c)} should we use?`
        : `Could you check the ${targetName(c)}?`;
  const action =
    r.ui_mode === "VALUE_INPUT"
      ? `Open the attached source document, then use Telegram’s Reply on THIS message and enter the ${fieldName(r.field)}.${r.field === "gross_weight_kg" ? " Use kg, a dot for decimals, and no grouping commas (example format: 21707)." : r.field === "container_count" ? " Enter a positive whole number." : " Enter the complete value as written."}\nI’ll show you a preview before submitting it. If you can’t tell, use the button below to leave this case waiting for outside help.`
      : r.ui_mode === "CHOICE"
        ? "Check the attached documents and View details, then tap the option you want to submit. If none fits, choose None of these; the case will wait for outside help."
        : `${r.context_summary}\nTap Acknowledge external action to close this request. The case will still wait for outside help—it won’t be marked verified.`;
  const mismatch = mismatchSummary(c);
  return `${heading}\n${c.email.subject}\n\n${action}${mismatch ? `\n\nStill needs correction: ${mismatch}. Resolving this review won’t erase that difference.` : ""}\n\n${demo}\nSI = shipping instructions · BL = bill of lading`;
}
export function outcomeCopy(c: Case) {
  const mismatch = mismatchSummary(c);
  let text =
    c.workflow_status === "BLOCKED_EXTERNAL"
      ? "Thanks—your response is recorded.\nThis case still needs outside help before verification can finish."
      : c.workflow_status === "AWAITING_HUMAN"
        ? "Thanks—that step is done.\nThere’s one more question to resolve. Use the new review message; your earlier reply won’t answer it."
        : c.workflow_status === "FAILED"
          ? "Your response is saved, but processing stopped.\nThe operator needs to investigate. Please don’t submit it again."
          : c.workflow_status === "PROCESSING"
            ? "Your response is saved.\nI’m still waiting for the result; earlier results are updating."
            : effectiveStatus(c) === "MISMATCH"
              ? `The check is finished, but corrections are still needed.\n${mismatch}\nPlease arrange a corrected document.`
              : "The check is finished—the compared values now match.\nNo correction is required for this result.";
  text += `\n\n${c.email.subject}\nThe original machine assessment is unchanged; this is the result after review.`;
  if (c.resolution?.value_source === "MANUAL_OVERRIDE")
    text +=
      "\nYour value is human-provided and ungrounded: it could not be verified from the source.";
  return `${text}\n\n${demo}`;
}
export function detailCopy(c: Case) {
  const r = c.review;
  const parts = [
    `Review details · ${c.email.subject}`,
    demo,
    `Current workflow: ${c.workflow_status}\nOperational result: ${effectiveStatus(c)}\nFrozen machine assessment: ${c.machine_assessment?.status ?? "not available"}\nFollow-up: ${c.follow_up}`,
  ];
  if (r)
    parts.push(
      `${r.question}\n${r.context_summary}\nTarget: ${targetName(c)}\nReview: ${r.review_id} (${r.status})`,
    );
  if (c.failure)
    parts.push(
      `Processing failure: ${c.failure.step}\nAttempts: ${c.failure.attempts}\n${c.failure.message}`,
    );
  for (const o of r?.options ?? []) {
    parts.push(
      `Option: ${o.label}${o.kind === "VALUE" ? `\nNormalized: ${o.value.normalized}\nEvidence: ${o.value.evidence.map((e) => e.source_text).join("; ") || "none—requires verification"}` : o.kind === "DOCUMENT" ? `\nDocument: ${o.document_id}; target role: ${r?.target_role}` : "\nLeaves the case waiting for outside help."}`,
    );
  }
  for (const f of c.fields.filter(
    (f) => f.field === r?.field || f.result === "MISMATCH",
  )) {
    parts.push(fieldName(f.field));
    for (const side of ["si", "bl"] as const) {
      const v = f[side];
      parts.push(
        `${side.toUpperCase()}: raw ${v?.raw ?? "unknown"}; normalized ${v?.normalized ?? "unknown"}\nOrigin: ${v?.value_origin ?? "unknown"}; ${v?.grounded ? "source-supported in simulator" : "not verified"}\nEvidence: ${v?.evidence.map((e) => `${e.document_id}: ${e.source_text}`).join("; ") || "none"}`,
      );
    }
  }
  parts.push(
    `Case: ${c.case_id}\nRun: ${c.run.run_id}\nUse the original review message to reply. These details do not submit a decision.`,
  );
  return parts.join("\n\n");
}
export function errorCopy(code: string) {
  if (
    ["STALE_RUN", "REVIEW_ALREADY_CLOSED", "DECISION_CONFLICT"].includes(code)
  )
    return "That review has already been handled or replaced. Send /reviews and open the current case; I won’t reuse your old answer.";
  if (["FORBIDDEN", "UNAUTHORIZED"].includes(code))
    return "I can’t use that button for this account or message. Open your own review through /reviews.";
  if (code === "NOT_FOUND")
    return "I couldn’t find that review. Send /reviews to refresh your queue.";
  if (code === "RATE_LIMITED")
    return "Too many attempts just now. Give it a moment, then open the current review. Nothing was automatically resubmitted.";
  return "I couldn’t submit that response. Check the current review and its allowed values, then try again. Nothing was automatically resubmitted.";
}
