import { randomUUID } from "node:crypto";
import type { Case, CaseSummary, Stats, Review } from "../shared/types";
import {
  assertDemo,
  categories,
  effectiveStatus,
  statsSchema,
  statuses,
  validateCase,
  workflows,
} from "../shared/validation";
import {
  auditDocuments,
  baselineTime,
  history,
  makeFixture,
  sourceContext,
  scenarios,
  type Scenario,
} from "./fixtures";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export const summary = (c: Case): CaseSummary => ({
  case_id: c.case_id,
  run_id: c.run.run_id,
  from: c.email.from,
  subject: c.email.subject,
  category: c.email.category,
  workflow_status: c.workflow_status,
  machine_status: c.machine_assessment?.status ?? null,
  review_reason: c.machine_assessment?.review_reason ?? null,
  final_status: effectiveStatus(c),
  mismatch_count: c.fields.filter((f) => f.result === "MISMATCH").length,
  has_open_review: c.review?.status === "OPEN",
  run_kind: c.run.kind,
  updated_at: c.updated_at,
});
export function statistics(
  cases: Case[],
  now = new Date().toISOString(),
): Stats {
  const counts = <T extends string>(keys: readonly T[]) =>
    Object.fromEntries(keys.map((k) => [k, 0])) as Record<T, number>;
  const s: Stats = {
    generated_at: now,
    run_kind: "DEMO",
    total_cases: cases.length,
    unclassified: 0,
    by_category: counts(categories),
    by_machine_status: counts(statuses),
    by_effective_status: counts(statuses),
    by_workflow: counts(workflows),
    bl_comparison: { total: 0, ok: 0, mismatch: 0, needs_review: 0 },
    awaiting_human_now: 0,
    auto_completed: 0,
    ai_assisted_cases: 0,
    ai_calls_total: 0,
    avg_processing_ms: null,
  };
  const durations: number[] = [];
  for (const c of cases) {
    assertDemo(c);
    s.by_workflow[c.workflow_status]++;
    if (c.email.category) s.by_category[c.email.category]++;
    else s.unclassified++;
    if (c.machine_assessment) {
      s.by_machine_status[c.machine_assessment.status]++;
      if (c.email.category === "BL_COMPARISON") {
        s.bl_comparison.total++;
        s.bl_comparison[
          c.machine_assessment.status === "OK"
            ? "ok"
            : c.machine_assessment.status === "MISMATCH"
              ? "mismatch"
              : "needs_review"
        ]++;
      }
    }
    const e = effectiveStatus(c);
    if (e) s.by_effective_status[e]++;
    if (
      c.review?.status === "OPEN" &&
      ["AWAITING_HUMAN", "BLOCKED_EXTERNAL"].includes(c.workflow_status)
    )
      s.awaiting_human_now++;
    if (
      c.workflow_status === "COMPLETED" &&
      !c.history.some(
        (h) => h.run_id === c.run.run_id && h.type === "REVIEW_CREATED",
      )
    )
      s.auto_completed++;
    if (c.metrics.ai_calls > 0) s.ai_assisted_cases++;
    s.ai_calls_total += c.metrics.ai_calls;
    if (c.metrics.processing_ms !== null)
      durations.push(c.metrics.processing_ms);
  }
  s.avg_processing_ms = durations.length
    ? durations.reduce((a, b) => a + b, 0) / durations.length
    : null;
  return statsSchema.parse(s);
}
export class DemoStore {
  cases = new Map<string, Case>();
  documents = new Map<string, string>();
  archivedReviews = new Map<string, Review>();
  jobs = new Map<string, { runId: string; due: number; scenario: Scenario }>();
  fault: "none" | "outage" | "slow" | "denied" = "none";
  constructor() {
    this.reset();
  }
  reset(empty = false) {
    this.cases.clear();
    this.documents.clear();
    this.archivedReviews.clear();
    this.jobs.clear();
    this.fault = "none";
    if (!empty)
      for (const [scenario] of scenarios) {
        const c = makeFixture(scenario, this.documents);
        auditDocuments(c, this.documents);
        this.cases.set(c.case_id, c);
        for (const h of c.history) {
          const r = h.details?.review as Review | undefined;
          if (r?.status === "CLOSED") this.archivedReviews.set(r.review_id, r);
        }
      }
  }
  get(id: string) {
    const c = this.cases.get(id);
    if (!c)
      throw new ApiError(
        404,
        "NOT_FOUND",
        "Case unavailable in this demo scope.",
      );
    assertDemo(c);
    return c;
  }
  list(query: Record<string, unknown> = {}) {
    return [...this.cases.values()]
      .map((c) => {
        assertDemo(c);
        return summary(c);
      })
      .filter(
        (c) =>
          (!query.workflow_status ||
            c.workflow_status === query.workflow_status) &&
          (!query.category || c.category === query.category) &&
          (!query.final_status || c.final_status === query.final_status) &&
          (query.has_open_review === undefined ||
            String(c.has_open_review) === query.has_open_review),
      );
  }
  document(id: string) {
    const d = [...this.cases.values()]
      .flatMap((c) => {
        assertDemo(c);
        return c.documents;
      })
      .find((d) => d.document_id === id && d.demo_safe);
    if (!d || !this.documents.has(id))
      throw new ApiError(
        404,
        "NOT_FOUND",
        "Document unavailable in this demo scope.",
      );
    return { meta: d, text: this.documents.get(id)! };
  }
  create(emailId: string) {
    const scenario = scenarios.find(([s]) => `demo_${s}` === emailId)?.[0];
    if (!scenario)
      throw new ApiError(
        404,
        "NOT_FOUND",
        "Only approved synthetic fixtures can be processed.",
      );
    if (this.cases.has(emailId))
      return { status: 200, body: this.get(emailId) };
    return { status: 202, body: this.begin(scenario) };
  }
  reprocess(id: string) {
    this.get(id);
    const scenario = scenarios.find(([s]) => `demo_${s}` === id)![0];
    return this.begin(scenario);
  }
  private begin(scenario: Scenario) {
    const id = `demo_${scenario}`,
      old = this.cases.get(id),
      runId = `demo_${randomUUID()}`,
      now = new Date().toISOString();
    const c = makeFixture("processing", this.documents, runId);
    c.case_id = id;
    c.email.email_id = id;
    c.email.subject = scenarios.find((s) => s[0] === scenario)![1];
    c.run.started_at = now;
    c.updated_at = now;
    c.created_at = old?.created_at ?? now;
    c.email.received_at = old
      ? old.email.received_at
      : makeFixture(scenario, new Map()).email.received_at;
    c.history = [];
    if (old) {
      c.history = structuredClone(old.history);
      c.documents = structuredClone(old.documents);
      if (old.review?.status === "OPEN") {
        const r = {
          ...old.review,
          status: "CLOSED" as const,
          close_reason: "SUPERSEDED" as const,
          closed_at: now,
        };
        this.archivedReviews.set(r.review_id, r);
        c.history.push({
          event_id: randomUUID(),
          run_id: old.run.run_id,
          at: now,
          type: "REVIEW_SUPERSEDED",
          actor: { kind: "SYSTEM", id: null },
          summary: "Previous review superseded by explicit replay.",
          details: { review: r },
        });
      }
      history(
        c,
        "CASE_REPROCESSED",
        "Synthetic replay queued. New run; no prior human override carried forward.",
        now,
        sourceContext(c, scenario),
      );
    } else
      history(
        c,
        "CASE_CREATED",
        "Approved synthetic fixture queued.",
        now,
        sourceContext(c, scenario),
      );
    this.cases.set(id, validateCase(c));
    this.jobs.set(id, {
      runId,
      due: Date.now() + 8000,
      scenario:
        scenario === "processing" || scenario === "superseded"
          ? "match"
          : scenario === "human-resolved" ||
              scenario === "document-confirmed" ||
              scenario === "accepted-processing" ||
              scenario === "failed-after"
            ? "field-input"
            : scenario === "blocked-acknowledged"
              ? "blocked-open"
              : scenario === "sequential-second"
                ? "sequential-first"
                : scenario,
    });
    return c;
  }
  advance() {
    for (const c of this.cases.values())
      if (c.workflow_status === "PROCESSING" && !this.jobs.has(c.case_id)) {
        this.jobs.set(c.case_id, {
          runId: c.run.run_id,
          due: 0,
          scenario:
            c.case_id === "demo_accepted-processing"
              ? "human-resolved"
              : "match",
        });
      }
    for (const j of this.jobs.values()) j.due = 0;
    this.tick();
  }
  tick(now = Date.now()) {
    for (const [id, job] of this.jobs) {
      if (job.due > now) continue;
      this.jobs.delete(id);
      const old = this.cases.get(id);
      if (!old || old.run.run_id !== job.runId) continue;
      const c = makeFixture(job.scenario, this.documents, job.runId);
      c.case_id = id;
      c.email.email_id = id;
      c.email.subject = old.email.subject;
      c.created_at = old.created_at;
      c.email.received_at = old.email.received_at;
      c.run.started_at = old.run.started_at;
      c.updated_at = new Date(now).toISOString();
      if (c.completed_at) c.completed_at = c.updated_at;
      if (c.review) c.review.case_id = id;
      const sourceEvent = c.history.find((h) => h.type === "EMAIL_CLASSIFIED");
      if (sourceEvent) sourceEvent.details = sourceContext(c, job.scenario);
      c.history = [
        ...old.history,
        ...c.history
          .filter((h) => h.type !== "CASE_CREATED")
          .map((h) => ({ ...h, event_id: randomUUID(), at: c.updated_at })),
      ];
      // A simulated accepted-decision completion must preserve its frozen assessment.
      if (old.machine_assessment) c.machine_assessment = old.machine_assessment;
      auditDocuments(c, this.documents);
      this.cases.set(id, validateCase(c));
    }
  }
  review(id: string) {
    const active = [...this.cases.values()].find(
      (c) => c.review?.review_id === id,
    );
    if (active) return active.review!;
    const archived = this.archivedReviews.get(id);
    if (archived) return archived;
    throw new ApiError(
      404,
      "NOT_FOUND",
      "Review unavailable in this demo scope.",
    );
  }
}
