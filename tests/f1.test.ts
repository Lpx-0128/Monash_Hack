import test from "node:test";
import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { randomUUID } from "node:crypto";
import { createApp } from "../server/app";
import { caseSchema, errorSchema } from "../shared/validation";
import { parseProposal } from "../shared/decisions";
import type { Case } from "../shared/types";
import { DemoStore } from "../server/store";
async function harness(stateFile?: string, cookie = "") {
  const app = createApp({ stateFile }),
    server = app.app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const h = {
    cookie,
    async request(path: string, body?: unknown) {
      const r = await fetch(base + path, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          cookie: h.cookie,
          ...(body === undefined ? {} : { "content-type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      h.cookie = r.headers.get("set-cookie")?.split(";")[0] ?? h.cookie;
      return r;
    },
    async get(id: string) {
      return caseSchema.parse(
        await (await h.request(`/api/v1/cases/demo_${id}`)).json(),
      );
    },
    async advance() {
      await h.request("/api/demo/advance", {});
    },
    async close() {
      app.dispose();
      await new Promise<void>((resolve, reject) =>
        server.close((e) => (e ? reject(e) : resolve())),
      );
    },
  };
  return h;
}
const body = (c: Case, extra: object) => ({
  review_id: c.review!.review_id,
  run_id: c.run.run_id,
  channel: "DASHBOARD",
  actor_id: "demo-guest",
  ...extra,
});
const provide = (c: Case, value: string | number) =>
  body(c, {
    action: "PROVIDE_VALUE",
    field: c.review!.field,
    side: c.review!.side,
    value,
  });
const override = (c: Case, value: string | number) => ({
  review_id: c.review!.review_id,
  run_id: c.run.run_id,
  field: c.review!.field,
  side: c.review!.side,
  proposed_value: value,
  confirmed: true,
});
async function send(
  h: Awaited<ReturnType<typeof harness>>,
  c: Case,
  d: object,
  status = 202,
  code?: string,
) {
  const r = await h.request(
    `/api/v1/reviews/${c.review!.review_id}/decision`,
    d,
  );
  assert.equal(
    r.status,
    status,
    await (r.status !== status ? r.clone().text() : Promise.resolve("")),
  );
  const result = await r.json();
  if (code) assert.equal(errorSchema.parse(result).error.code, code);
  if (status === 202) {
    const accepted = caseSchema.parse(result);
    assert.equal(accepted.workflow_status, "PROCESSING");
    assert.equal(accepted.review!.status, "CLOSED");
    assert.deepEqual(accepted.machine_assessment, c.machine_assessment);
    assert.equal(accepted.resolution?.review_id, c.resolution?.review_id);
  }
  return result;
}
test("F1 HTTP grounded value completes; machine result stays frozen", async () => {
  const h = await harness();
  try {
    const c = await h.get("grounded-input");
    await send(h, c, provide(c, "21707 kg"));
    await h.advance();
    const done = await h.get("grounded-input");
    assert.equal(done.workflow_status, "COMPLETED");
    assert.equal(done.resolution!.final_status, "OK");
    assert.equal(done.fields[6].bl!.value_origin, "DOCUMENT_CONFIRMED");
    assert.equal(done.fields[6].bl!.grounded, true);
    assert.ok(done.fields[6].bl!.evidence.length);
    assert.deepEqual(done.machine_assessment, c.machine_assessment);
  } finally {
    await h.close();
  }
});
test("F1 HTTP grounding rejection, exact override binding and operational mismatch", async () => {
  const h = await harness();
  try {
    const c = await h.get("field-input"),
      d = provide(c, 22000);
    await send(h, c, d, 422, "VALUE_NOT_FOUND_IN_DOCUMENT");
    assert.deepEqual(await h.get("field-input"), c);
    for (const change of [
      { review_id: "wrong" },
      { run_id: "wrong" },
      { field: "container_count" },
      { side: "SI" },
      { proposed_value: 22001 },
    ])
      await send(
        h,
        c,
        { ...d, override_confirmation: { ...override(c, 22000), ...change } },
        422,
        "INVALID_CONFIRMATION",
      );
    await send(h, c, { ...d, override_confirmation: override(c, 22000) });
    await h.advance();
    const done = await h.get("field-input");
    assert.equal(done.resolution!.final_status, "MISMATCH");
    assert.equal(done.follow_up, "CORRECTION_REQUIRED");
    assert.equal(done.fields[6].bl!.grounded, false);
    assert.equal(done.fields[6].bl!.value_origin, "MANUAL_OVERRIDE");
    assert.deepEqual(done.fields[6].bl!.override_confirmations, [
      override(c, 22000),
    ]);
    assert.deepEqual(done.machine_assessment, c.machine_assessment);
  } finally {
    await h.close();
  }
});
test("F1 HTTP candidate and document-role selection, including unsupported candidate", async () => {
  const h = await harness();
  try {
    for (const [id, option] of [
      ["candidate-choice", "weight-21707"],
      ["document-choice", null],
      ["unsupported-candidate", "weight-22000"],
    ] as const) {
      const c = await h.get(id);
      const optionId =
        option ??
        c.review!.options!.find((o) => o.kind === "DOCUMENT")!.option_id;
      const d = body(c, { action: "SELECT_OPTION", option_id: optionId });
      if (id === "unsupported-candidate") {
        await send(h, c, d, 422, "VALUE_NOT_FOUND_IN_DOCUMENT");
        Object.assign(d, { override_confirmation: override(c, 23000) });
      }
      await send(h, c, d);
      await h.advance();
      const done = await h.get(id);
      assert.equal(done.workflow_status, "COMPLETED");
      assert.equal(
        done.fields[6].bl!.normalized,
        id === "unsupported-candidate" ? 23000 : 21707,
      );
      if (id === "document-choice") {
        assert.equal(done.documents.filter((d) => d.role === "BL").length, 1);
        assert.ok(
          done.fields.every(
            (f) =>
              f.bl?.evidence[0].document_id ===
              done.documents.find((d) => d.role === "BL")!.document_id,
          ),
        );
      }
      assert.deepEqual(done.machine_assessment, c.machine_assessment);
    }
  } finally {
    await h.close();
  }
});
test("F1 HTTP acknowledgment and both escape modes remain external blocks", async () => {
  const h = await harness();
  try {
    for (const id of [
      "blocked-open",
      "field-input",
      "candidate-choice",
      "document-choice",
    ]) {
      const c = await h.get(id);
      await send(
        h,
        c,
        body(
          c,
          c.review!.ui_mode === "CHOICE"
            ? { action: "SELECT_OPTION", option_id: "NONE_OF_THESE" }
            : { action: "ACKNOWLEDGE" },
        ),
      );
      await h.advance();
      const done = await h.get(id);
      assert.equal(done.workflow_status, "BLOCKED_EXTERNAL");
      assert.equal(done.review!.status, "CLOSED");
      assert.equal(done.follow_up, "AWAIT_EXTERNAL");
      assert.equal(done.completed_at, null);
      assert.equal(done.resolution!.final_status, "NEEDS_REVIEW");
    }
  } finally {
    await h.close();
  }
});
test("F1 HTTP sequential field order and SI-before-BL with frozen machine result", async () => {
  const h = await harness();
  try {
    for (const id of ["sequential-first", "both-sides"]) {
      let c = await h.get(id);
      const machine = c.machine_assessment;
      assert.equal(
        c.review!.field,
        id === "both-sides" ? "gross_weight_kg" : "container_count",
      );
      assert.equal(c.review!.side, id === "both-sides" ? "SI" : "BL");
      await send(h, c, provide(c, id === "both-sides" ? 21707 : 3));
      await h.advance();
      c = await h.get(id);
      assert.equal(c.workflow_status, "AWAITING_HUMAN");
      assert.equal(c.resolution!.final_status, "NEEDS_REVIEW");
      assert.equal(c.review!.field, "gross_weight_kg");
      assert.equal(c.review!.side, "BL");
      const d = provide(c, 21707);
      if (id === "sequential-first")
        Object.assign(d, { override_confirmation: override(c, 21707) });
      await send(h, c, d);
      await h.advance();
      c = await h.get(id);
      assert.equal(c.workflow_status, "COMPLETED");
      assert.deepEqual(c.machine_assessment, machine);
      assert.equal(
        c.history.filter((h) => h.type === "DECISION_APPLIED").length,
        2,
      );
    }
  } finally {
    await h.close();
  }
});
test("F1 known mismatch persists while awaiting review and after completion", async () => {
  const h = await harness();
  try {
    const c = await h.get("mismatch-review");
    assert.equal(c.machine_assessment!.status, "NEEDS_REVIEW");
    assert.deepEqual(c.machine_assessment!.defect_fields, []);
    assert.equal(c.fields[5].result, "MISMATCH");
    await send(h, c, {
      ...provide(c, 21707),
      override_confirmation: override(c, 21707),
    });
    await h.advance();
    const done = await h.get("mismatch-review");
    assert.equal(done.resolution!.final_status, "MISMATCH");
    assert.deepEqual(done.resolution!.final_defect_fields, ["container_count"]);
    assert.equal(done.follow_up, "CORRECTION_REQUIRED");
  } finally {
    await h.close();
  }
});
test("F1 HTTP rejects malformed, wrong-target, wrong-actor, stale and competing actions", async () => {
  const h = await harness();
  try {
    const c = await h.get("grounded-input"),
      d = provide(c, 21707);
    for (const [patch, status, code] of [
      [{ field: "container_count" }, 422, "ACTION_NOT_ALLOWED"],
      [{ side: "SI" }, 422, "ACTION_NOT_ALLOWED"],
      [
        {
          action: "SELECT_OPTION",
          option_id: "bad",
          field: undefined,
          side: undefined,
          value: undefined,
        },
        422,
        "ACTION_NOT_ALLOWED",
      ],
      [{ actor_id: "admin" }, 403, "FORBIDDEN"],
      [{ run_id: "stale" }, 409, "STALE_RUN"],
      [{ review_id: "other" }, 422, "INVALID_VALUE"],
      [{ value: 0 }, 422, "INVALID_VALUE"],
      [{ grounded: true }, 422, "INVALID_VALUE"],
    ] as const)
      await send(h, c, { ...d, ...patch }, status, code);
    assert.deepEqual(await h.get("grounded-input"), c);
    const race = await Promise.all([
      h.request(`/api/v1/reviews/${c.review!.review_id}/decision`, d),
      h.request(`/api/v1/reviews/${c.review!.review_id}/decision`, d),
    ]);
    assert.deepEqual(race.map((r) => r.status).sort(), [202, 409]);
    await h.request(`/api/v1/cases/${c.case_id}/reprocess`, {});
    await send(h, c, d, 409, "REVIEW_ALREADY_CLOSED");
    await h.advance();
    const fresh = await h.get("grounded-input");
    assert.equal(fresh.resolution, null);
    assert.notEqual(fresh.run.run_id, c.run.run_id);
  } finally {
    await h.close();
  }
});
test("F1 HTTP rate limits invalid attempts and denies unauthorized scope", async () => {
  const h = await harness();
  try {
    const c = await h.get("candidate-choice");
    for (let i = 0; i < 12; i++)
      await send(
        h,
        c,
        body(c, { action: "SELECT_OPTION", option_id: "not-member" }),
        422,
        "OPTION_NOT_FOUND",
      );
    await send(
      h,
      c,
      body(c, { action: "SELECT_OPTION", option_id: "weight-21707" }),
      429,
      "RATE_LIMITED",
    );
    assert.deepEqual(await h.get("candidate-choice"), c);
    await h.request("/api/demo/fault", { mode: "denied" });
    await send(
      h,
      c,
      body(c, { action: "SELECT_OPTION", option_id: "weight-21707" }),
      403,
      "FORBIDDEN",
    );
  } finally {
    await h.close();
  }
});
test("F1 lost response retains acceptance; resumption failure preserves unapplied decision", async () => {
  const h = await harness();
  try {
    const c = await h.get("grounded-input");
    await h.request("/api/demo/decision-fault", { mode: "lost-response" });
    await assert.rejects(
      h.request(
        `/api/v1/reviews/${c.review!.review_id}/decision`,
        provide(c, 21707),
      ),
    );
    assert.equal((await h.get("grounded-input")).review!.status, "CLOSED");
    await h.advance();
    assert.equal((await h.get("grounded-input")).workflow_status, "COMPLETED");
    const f = await h.get("resume-failure");
    await send(h, f, {
      ...provide(f, 21707),
      override_confirmation: override(f, 21707),
    });
    await h.advance();
    const failed = await h.get("resume-failure");
    assert.equal(failed.workflow_status, "FAILED");
    assert.equal(failed.failure!.attempts, 2);
    assert.equal(failed.resolution, null);
    assert.ok(failed.history.some((h) => h.type === "DECISION_RECEIVED"));
    assert.deepEqual(failed.machine_assessment, f.machine_assessment);
  } finally {
    await h.close();
  }
});
test("F1 accepted pending work survives a server restart and applies once", async () => {
  const path = `.local/tests/state-${randomUUID()}.json`;
  let h = await harness(path);
  try {
    const c = await h.get("grounded-input");
    await send(h, c, provide(c, 21707));
    const cookie = h.cookie;
    await h.close();
    h = await harness(path, cookie);
    assert.equal((await h.get("grounded-input")).workflow_status, "PROCESSING");
    await h.advance();
    await h.advance();
    const done = await h.get("grounded-input");
    assert.equal(done.workflow_status, "COMPLETED");
    assert.equal(
      done.history.filter((e) => e.type === "DECISION_APPLIED").length,
      1,
    );
  } finally {
    await h.close();
  }
});
test("F1 canonical input rejects unsafe or ambiguous numeric syntax", () => {
  for (const value of [
    "",
    "0",
    "-1",
    "NaN",
    "1,234",
    "1e3",
    "2 tons",
    "9007199254740992",
    "1.1234567890123456789",
  ])
    assert.throws(() => parseProposal("gross_weight_kg", value));
  assert.throws(() => parseProposal("container_count", "1.5"));
  assert.equal(parseProposal("gross_weight_kg", "21707.50 kg"), 21707.5);
  assert.equal(parseProposal("container_count", "3"), 3);
  assert.equal(
    parseProposal("shipper", "  Meridian\n10 Harbour Road "),
    "meridian 10 harbour road",
  );
});
