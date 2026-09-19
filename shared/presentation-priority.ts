import type { Case, CaseSummary, FieldValue } from "./types";

export type WorkHint = {
  group: "quick" | "investigate" | "waiting" | "done";
  label: string;
};
export type CaseSort = "investigation" | "quick" | "recent";
const investigation = (action: string): WorkHint => ({
  group: "investigate",
  label: `Needs investigation · ${action}`,
});
// Presentation guidance only. Never determines allowed actions or backend grounding.
export function workHint(summary: CaseSummary, detail?: Case): WorkHint {
  if (summary.workflow_status === "FAILED")
    return investigation("Resolve processing failure");
  if (summary.workflow_status === "BLOCKED_EXTERNAL")
    return investigation("Obtain missing source");
  if (summary.workflow_status === "PROCESSING")
    return { group: "waiting", label: "Processing · wait for result" };
  if (summary.mismatch_count > 0 || summary.final_status === "MISMATCH")
    return investigation("Check corrections needed");
  if (!summary.has_open_review)
    return { group: "done", label: "No review needed" };
  if (
    !detail ||
    detail.run.run_id !== summary.run_id ||
    detail.updated_at !== summary.updated_at ||
    detail.review?.status !== "OPEN"
  )
    return investigation("Inspect current review");
  const r = detail.review;
  if (r.ui_mode === "ACKNOWLEDGE")
    return investigation("Arrange external action");
  const evidenceAvailable = (v: FieldValue) =>
    v.normalized !== null &&
    v.value_origin !== "MANUAL_OVERRIDE" &&
    v.evidence.length > 0 &&
    v.evidence.every((e) =>
      detail.documents.some(
        (d) => d.document_id === e.document_id && d.parse_status === "OK",
      ),
    );
  if (r.ui_mode === "CHOICE") {
    const choices = (r.options ?? []).filter((o) => o.kind !== "ESCAPE");
    if (
      choices.length &&
      choices.every((o) =>
        o.kind === "VALUE"
          ? o.value.grounded && evidenceAvailable(o.value)
          : o.kind === "DOCUMENT" &&
            detail.documents.some(
              (d) => d.document_id === o.document_id && d.parse_status === "OK",
            ),
      )
    )
      return {
        group: "quick",
        label: `Quick review · ${r.target_role ? `Choose ${r.target_role} document` : "Choose evidenced value"}`,
      };
    return investigation("Check uncertain choices");
  }
  const otherSide = detail.fields.find((f) => f.field === r.field)?.[
    r.side === "SI" ? "bl" : "si"
  ];
  if (
    detail.fields.some(
      (f) => f.field !== r.field && f.result === "NOT_COMPARABLE",
    ) ||
    !otherSide?.grounded
  )
    return investigation("Resolve multiple uncertainties");
  const value = detail.fields.find((f) => f.field === r.field)?.[
    r.side === "SI" ? "si" : "bl"
  ];
  if (r.side && value && evidenceAvailable(value))
    return { group: "quick", label: `Quick review · Confirm ${r.side} value` };
  return investigation("Inspect missing or uncertain value");
}
export function compareWork(
  a: CaseSummary,
  b: CaseSummary,
  hints: Record<string, WorkHint>,
  sort: CaseSort,
): number {
  if (sort !== "recent") {
    const ranks =
      sort === "quick"
        ? { quick: 0, investigate: 1, waiting: 2, done: 3 }
        : { investigate: 0, quick: 1, waiting: 2, done: 3 };
    const difference =
      ranks[(hints[a.case_id] ?? workHint(a)).group] -
      ranks[(hints[b.case_id] ?? workHint(b)).group];
    if (difference) return difference;
  }
  return (
    b.updated_at.localeCompare(a.updated_at) ||
    a.case_id.localeCompare(b.case_id)
  );
}
