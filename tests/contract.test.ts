import test from "node:test";
import assert from "node:assert/strict";
import { auditDocuments, makeFixture, scenarios } from "../server/fixtures";
import { DemoStore, statistics } from "../server/store";
import { caseSchema, statsSchema, validateCase } from "../shared/validation";
import type { Case } from "../shared/types";
import { createHash } from "node:crypto";

test("Every required fixture passes wire/invariant validation and exact source audit", () => {
  for (const [s] of scenarios) {
    const docs = new Map<string, string>();
    const c = makeFixture(s, docs);
    assert.equal(validateCase(c).schema_version, "2.1.1", s);
    auditDocuments(c, docs);
  }
});
const invalid: (readonly [string, (c: Case) => void])[] = [
  [
    "missing required property",
    (c) => {
      delete (c as Partial<Case>).schema_version;
    },
  ],
  [
    "unknown enum",
    (c) => {
      (c as unknown as { workflow_status: string }).workflow_status = "DONE";
    },
  ],
  [
    "nullable classification after assessment",
    (c) => {
      c.email.category = null;
    },
  ],
  [
    "six settled fields",
    (c) => {
      c.fields.pop();
    },
  ],
  [
    "duplicate canonical field",
    (c) => {
      c.fields[6] = c.fields[5];
    },
  ],
  [
    "blank comparable value",
    (c) => {
      c.fields[0].bl = null;
    },
  ],
  [
    "false numeric match",
    (c) => {
      c.fields[5].bl!.normalized = 4;
    },
  ],
  [
    "count is fractional",
    (c) => {
      c.fields[5].bl!.normalized = 3.5;
    },
  ],
  [
    "negative numeric field",
    (c) => {
      c.fields[6].bl!.normalized = -1;
    },
  ],
  [
    "number in text field",
    (c) => {
      c.fields[0].bl!.normalized = 123;
    },
  ],
  [
    "incorrect follow up",
    (c) => {
      c.follow_up = "AWAIT_EXTERNAL";
    },
  ],
  [
    "completed timestamp absent",
    (c) => {
      c.completed_at = null;
    },
  ],
  [
    "ungrounded document confirmed",
    (c) => {
      c.fields[6].bl!.value_origin = "DOCUMENT_CONFIRMED";
      c.fields[6].bl!.grounded = false;
    },
  ],
  [
    "laundered override",
    (c) => {
      c.fields[6].bl!.value_origin = "MANUAL_OVERRIDE";
    },
  ],
  [
    "missing evidence reference",
    (c) => {
      c.fields[0].si!.evidence[0].document_id = "nonexistent";
    },
  ],
  [
    "invalid assessment roll up",
    (c) => {
      c.machine_assessment!.status = "NEEDS_REVIEW";
    },
  ],
  [
    "not comparable missing cause",
    (c) => {
      c.fields[0].result = "NOT_COMPARABLE";
    },
  ],
  [
    "failure hidden by completed",
    (c) => {
      c.workflow_status = "FAILED";
    },
  ],
];
for (const [name, mutate] of invalid)
  test(`Reject contract violation: ${name}`, () => {
    const c = makeFixture("match", new Map());
    mutate(c);
    assert.equal(caseSchema.safeParse(c).success, false);
  });
test("Choice requires NONE_OF_THESE, allowed action and exact target", () => {
  for (const mutate of [
    (c: Case) => {
      c.review!.options!.pop();
    },
    (c: Case) => {
      c.review!.side = null;
    },
    (c: Case) => {
      c.review!.allowed_actions = ["ACKNOWLEDGE"];
    },
    (c: Case) => {
      c.review!.run_id = "old";
    },
  ]) {
    const c = makeFixture("candidate-choice", new Map());
    mutate(c);
    assert.equal(caseSchema.safeParse(c).success, false);
  }
});
test("Frozen NEEDS_REVIEW stays distinct from manual operational OK", () => {
  const c = makeFixture("human-resolved", new Map());
  assert.equal(c.machine_assessment!.status, "NEEDS_REVIEW");
  assert.equal(c.resolution!.final_status, "OK");
  assert.equal(c.fields[6].bl!.grounded, false);
  assert.equal(c.fields[6].bl!.override_confirmations[0].proposed_value, 21707);
});
test("Acknowledgment remains blocked and sequential resolution remains NEEDS_REVIEW", () => {
  const c = makeFixture("blocked-acknowledged", new Map());
  assert.equal(c.workflow_status, "BLOCKED_EXTERNAL");
  assert.equal(c.completed_at, null);
  assert.equal(c.review!.status, "CLOSED");
  const second = makeFixture("sequential-second", new Map());
  assert.equal(second.resolution!.final_status, "NEEDS_REVIEW");
  assert.equal(second.review!.field, "gross_weight_kg");
  assert.equal(second.fields[5].bl!.value_origin, "DOCUMENT_CONFIRMED");
});
test("G2 fixture audit rejects seal-number grounding even with valid source/hash and matching digits", () => {
  const docs = new Map<string, string>(),
    c = makeFixture("match", docs);
  const e = c.fields[6].bl!.evidence[0];
  const text = docs
    .get(e.document_id)!
    .replace(e.source_text, "Seal reference: 21707");
  docs.set(e.document_id, text);
  const d = c.documents.find((d) => d.document_id === e.document_id)!;
  d.content_hash = createHash("sha256").update(text).digest("hex");
  d.size_bytes = Buffer.byteLength(text);
  e.source_text = "Seal reference: 21707";
  if (e.locator.kind === "text_range")
    e.locator.end = e.locator.start + e.source_text.length;
  assert.throws(() => auditDocuments(c, docs), /support field\/value/);
});
test("Direct human override confirmation cannot migrate to a different value, field, side or run", () => {
  for (const key of ["proposed_value", "field", "side", "run_id"] as const) {
    const c = makeFixture("human-resolved", new Map());
    const o = c.fields[6].bl!.override_confirmations[0];
    if (key === "proposed_value") o[key] = 22000;
    else if (key === "field") o[key] = "container_count";
    else if (key === "side") o[key] = "SI";
    else o[key] = "stale";
    assert.equal(caseSchema.safeParse(c).success, false);
  }
});
test("Stats count current run, unassessed and historical reviews correctly", () => {
  const s = new DemoStore(),
    stats = statistics([...s.cases.values()]);
  assert.equal(stats.total_cases, 18);
  assert.equal(stats.unclassified, 3);
  assert.equal(stats.by_machine_status.OK, 2);
  assert.equal(stats.by_machine_status.MISMATCH, 1);
  assert.equal(stats.by_machine_status.NEEDS_REVIEW, 12);
  assert.equal(stats.awaiting_human_now, 7);
  assert.equal(stats.auto_completed, 3);
  assert.equal(stats.ai_assisted_cases, 0);
  assert.equal(stats.by_workflow.FAILED, 2);
  const empty = statistics([]);
  assert.equal(empty.total_cases, 0);
  assert.equal(empty.avg_processing_ms, null);
  assert.equal(
    statsSchema.safeParse({ ...empty, total_cases: 1 }).success,
    false,
  );
});
test("Replay supersedes old review, resets override and rejects stale job commits", () => {
  const s = new DemoStore(),
    old = s.get("demo_field-input").review!;
  const next = s.reprocess("demo_field-input");
  assert.equal(s.review(old.review_id).close_reason, "SUPERSEDED");
  assert.equal(next.machine_assessment, null);
  const newer = s.reprocess("demo_field-input");
  s.jobs.set(newer.case_id, {
    runId: next.run.run_id,
    due: 0,
    scenario: "match",
  });
  s.tick();
  assert.equal(s.get(newer.case_id).run.run_id, newer.run.run_id);
  assert.equal(s.get(newer.case_id).workflow_status, "PROCESSING");
  s.reprocess("demo_human-resolved");
  s.advance();
  assert.equal(s.get("demo_human-resolved").resolution, null);
  assert.equal(s.get("demo_human-resolved").review!.status, "OPEN");
});
test("Duplicate create preserves actual run and new create returns processing", () => {
  const s = new DemoStore(),
    original = s.get("demo_match");
  assert.equal(s.create("demo_match").status, 200);
  assert.equal(s.create("demo_match").body.run.run_id, original.run.run_id);
  s.reset(true);
  assert.equal(s.create("demo_match").status, 202);
  assert.equal(s.get("demo_match").email.category, null);
  s.advance();
  assert.equal(s.get("demo_match").workflow_status, "COMPLETED");
});
