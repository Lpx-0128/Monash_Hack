import test from "node:test";
import assert from "node:assert/strict";
import { makeFixture } from "../server/fixtures";
import { summary } from "../server/store";
import { workHint, compareWork } from "../shared/presentation-priority";

test("Work recommendations depend on current evidence, never fixture names or inferred grounding", () => {
  const quick = makeFixture("grounded-input", new Map());
  const s = summary(quick);
  assert.equal(workHint(s, quick).group, "quick");
  quick.email.subject = "Missing source misleading title";
  assert.equal(workHint(s, quick).group, "quick");
  const unknown = structuredClone(quick);
  unknown.fields.find((f) => f.field === unknown.review!.field)!.bl!.evidence =
    [];
  assert.equal(workHint(s, unknown).group, "investigate");
  const stale = structuredClone(quick);
  stale.run.run_id = "older-run";
  assert.equal(workHint(s, stale).group, "investigate");
  for (const id of [
    "both-sides",
    "sequential-first",
    "field-input",
    "unsupported-candidate",
    "blocked-open",
    "mismatch-review",
    "failed-before",
  ] as const) {
    const c = makeFixture(id, new Map());
    assert.equal(workHint(summary(c), c).group, "investigate", id);
  }
  for (const id of ["candidate-choice", "document-choice"] as const) {
    const c = makeFixture(id, new Map());
    assert.equal(workHint(summary(c), c).group, "quick", id);
  }
  const hard = makeFixture("field-input", new Map()),
    h = summary(hard);
  const hints = {
    [s.case_id]: workHint(s, quick),
    [h.case_id]: workHint(h, hard),
  };
  assert.ok(compareWork(s, h, hints, "quick") < 0);
  assert.ok(compareWork(s, h, hints, "investigation") > 0);
});
