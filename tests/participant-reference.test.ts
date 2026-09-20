import test from "node:test";
import assert from "node:assert/strict";
import {
  mapParticipantToCase,
  participantEmailSchema,
} from "../shared/participant-mapping";
import { caseSchema } from "../shared/validation";
import { auditDocuments, makeFixture, scenarios } from "../server/fixtures";
import { DemoStore } from "../server/store";

const mappingContext = () => ({
  run: makeFixture("processing", new Map()).run,
  created_at: "2026-09-19T09:30:00Z",
});
test("AC-17: source without receipt maps to a valid processing Case without guessing or review", () => {
  const source = {
    email_id: "synthetic-input",
    from: "desk@demo.example",
    subject: "Check",
    body: "Sent: 2026-09-18T12:00:00Z",
    attachments: ["attachments/demo.txt"],
  };
  const before = structuredClone(source);
  const c = mapParticipantToCase(source, mappingContext());
  assert.equal(c.schema_version, "2.1.2");
  assert.equal(c.email.received_at, null);
  assert.equal(c.workflow_status, "PROCESSING");
  assert.equal(c.review, null);
  assert.equal(c.failure, null);
  assert.equal(c.created_at, mappingContext().created_at);
  assert.deepEqual(source, before);
  assert.deepEqual(c.history[0].details!.source_email, source);
});
test("AC-19: receipt is required but nullable in every workflow; invalid supplied times fail", () => {
  for (const [scenario] of scenarios) {
    const c = makeFixture(scenario, new Map());
    assert.equal(
      caseSchema.safeParse({ ...c, email: { ...c.email, received_at: null } })
        .success,
      true,
    );
    const { received_at, ...without } = c.email;
    assert.equal(caseSchema.safeParse({ ...c, email: without }).success, false);
    for (const invalid of ["", "yesterday", "2026-02-30T00:00:00Z", 0])
      assert.equal(
        caseSchema.safeParse({
          ...c,
          email: { ...c.email, received_at: invalid },
        }).success,
        false,
      );
    assert.equal(
      caseSchema.safeParse({ ...c, schema_version: "2.1" }).success,
      false,
    );
  }
  const source = {
    email_id: "demo",
    from: "desk@demo.example",
    subject: "Synthetic intake",
    body: "",
    attachments: [],
  };
  assert.equal(
    mapParticipantToCase(
      { ...source, received_at: "2026-09-19T17:00:00+08:00" },
      mappingContext(),
    ).email.received_at,
    "2026-09-19T09:00:00.000Z",
  );
  assert.throws(() =>
    mapParticipantToCase(
      { ...source, received_at: "not a date" },
      mappingContext(),
    ),
  );
});
test("AC-19: replay preserves source absence and creation time while advancing current run", () => {
  const s = new DemoStore();
  for (const id of ["demo_mismatch", "demo_match", "demo_processing"]) {
    const old = structuredClone(s.get(id));
    s.reprocess(id);
    const running = s.get(id);
    assert.equal(running.email.received_at, old.email.received_at);
    assert.equal(running.created_at, old.created_at);
    assert.notEqual(running.run.started_at, old.run.started_at);
    s.advance();
    const done = s.get(id);
    assert.equal(done.email.received_at, old.email.received_at);
    assert.equal(done.created_at, old.created_at);
    assert.equal(done.schema_version, "2.1.2");
  }
});
test("Every synthetic source follows the five-key participant shape and is explicitly fictional", () => {
  for (const [scenario] of scenarios) {
    const c = makeFixture(scenario, new Map());
    const metadata = c.history.find(
      (h) => h.run_id === c.run.run_id && h.type === "CASE_CREATED",
    )!.details!;
    const raw = participantEmailSchema.parse(metadata.source_email);
    assert.deepEqual(Object.keys(raw).sort(), [
      "attachments",
      "body",
      "email_id",
      "from",
      "subject",
    ]);
    assert.match(raw.body, /SYNTHETIC EMAIL/);
    assert.equal(
      metadata.receipt_timestamp_provenance,
      c.email.received_at === null
        ? "SOURCE_ABSENT"
        : "INDEPENDENTLY_AUTHORED_FICTIONAL_FIXTURE",
    );
    assert.equal(
      mapParticipantToCase(raw, mappingContext()).email.received_at,
      null,
    );
    assert.deepEqual(
      raw.attachments,
      c.documents.map((d) => `attachments/${d.filename}`),
    );
  }
});
test("Layout variations preserve complete address blocks and canonical equivalence", () => {
  const docs = new Map<string, string>(),
    c = makeFixture("match", docs);
  auditDocuments(c, docs);
  assert.equal(c.fields.length, 7);
  assert.ok(c.fields.every((f) => f.result === "MATCH"));
  assert.match(
    c.fields[0].si!.raw!,
    /Meridian Exports\n  10 Harbour Road\n  Suite 08/,
  );
  assert.equal(
    c.fields[0].si!.normalized,
    "meridian exports 10 harbour road suite 08, demo district",
  );
  assert.notEqual(c.fields[0].si!.raw, c.fields[0].bl!.raw);
  assert.equal(c.fields[5].si!.raw, "3 x 40'HC");
  assert.equal(c.fields[5].bl!.raw, "3 × 40HC");
  assert.equal(c.fields[5].bl!.normalized, 3);
  assert.equal(c.fields[6].si!.raw, "21,707 KG");
  assert.equal(c.fields[6].bl!.raw, "21707.00 kgs");
  assert.equal(c.fields[6].bl!.normalized, 21707);
  assert.match(
    c.fields[3].si!.evidence[0].source_text,
    /^Port of Loading \(POL\):/,
  );
  assert.match(c.fields[3].bl!.evidence[0].source_text, /^Load Port:/);
  for (const text of docs.values())
    assert.match(text, /comma groups thousands; dot is the decimal separator/);
});
test("Mismatch fixture still disagrees only on count despite alternate labels and formatting", () => {
  const c = makeFixture("mismatch", new Map());
  assert.deepEqual(
    c.fields.filter((f) => f.result === "MISMATCH").map((f) => f.field),
    ["container_count"],
  );
  assert.equal(c.fields[5].si!.normalized, 3);
  assert.equal(c.fields[5].bl!.normalized, 4);
  assert.equal(c.fields[6].result, "MATCH");
});
test("No-attachment intent remains unresolved under existing BL baseline, including after replay", () => {
  const s = new DemoStore();
  const verify = () => {
    const c = s.get("demo_no-attachment-intent");
    assert.equal(c.email.category, "BL_COMPARISON");
    assert.equal(c.machine_assessment!.status, "NEEDS_REVIEW");
    assert.equal(c.machine_assessment!.review_reason, "missing_attachment");
    assert.equal(c.workflow_status, "BLOCKED_EXTERNAL");
    assert.equal(c.completed_at, null);
    assert.deepEqual(c.documents, []);
    assert.ok(!c.history.some((h) => h.type === "DOCUMENT_PARSED"));
    assert.equal(c.fields.length, 7);
    assert.ok(
      c.fields.every(
        (f) => f.result === "NOT_COMPARABLE" && f.si === null && f.bl === null,
      ),
    );
    assert.match(c.review!.context_summary, /intent is unresolved/);
    assert.equal(c.machine_assessment!.has_defect, false);
    assert.deepEqual(c.machine_assessment!.defect_fields, []);
  };
  verify();
  s.reprocess("demo_no-attachment-intent");
  s.advance();
  verify();
});
test("Synthetic outcomes are authored independently of GENERAL submission placeholders", () => {
  assert.equal(
    makeFixture("non-bl", new Map()).email.category,
    "INVOICE_QUERY",
  );
  assert.equal(
    makeFixture("mismatch", new Map()).machine_assessment!.status,
    "MISMATCH",
  );
  assert.equal(
    makeFixture("no-attachment-intent", new Map()).machine_assessment!.status,
    "NEEDS_REVIEW",
  );
});
