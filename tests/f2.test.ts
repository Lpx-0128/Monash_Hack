import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { AddressInfo } from "node:net";
import { createApp } from "../server/app";
import type { ParticipantEmail } from "../shared/participant-mapping";
import { ReviewApi, RemoteError } from "../interaction/api";
import {
  ReviewEngine,
  type Button,
  type Incoming,
  type Transport,
} from "../interaction/engine";
const secret = "test-only-service-credential-0000000000";
class FakeTransport implements Transport {
  sendAttempts = 0;
  failEdit = false;
  edits: {
    chat: string;
    message: string;
    buttons: Button[][];
    text?: string;
  }[] = [];
  async edit(
    chat: string,
    message: string,
    buttons: Button[][],
    text?: string,
  ) {
    if (this.failEdit) throw new Error("Injected edit failure");
    this.edits.push({ chat, message, buttons, text });
  }
  messages: { id: string; chat: string; text: string; buttons: Button[][] }[] =
    [];
  files: { chat: string; filename: string; data: string }[] = [];
  failDocuments = false;
  failSend = false;
  async send(chat: string, text: string, buttons: Button[][] = []) {
    this.sendAttempts++;
    if (this.failSend) throw new Error("Injected send failure");
    const id = String(this.messages.length + 1);
    this.messages.push({ id, chat, text, buttons });
    return id;
  }
  async document(chat: string, file: { filename: string; data: string }) {
    if (this.failDocuments) throw new Error("Injected document failure");
    this.files.push({ chat, ...file });
    return "file-" + this.files.length;
  }
}
async function setup(t: any, dataset?: ParticipantEmail[]) {
  const dir = mkdtempSync(join(tmpdir(), "harbor-f2-")),
    app = createApp({
      dataset,
      stateFile: join(dir, "backend.json"),
      interaction: { token: secret, actors: ["101", "202"] },
    }),
    server = app.app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    api = new ReviewApi(base, secret, "101"),
    transport = new FakeTransport();
  let now = 100000,
    seq = 0;
  const recipients = [
    { actor: "101", chat: "101" },
    { actor: "202", chat: "202", operator: true },
  ];
  const make = () =>
    new ReviewEngine(
      join(dir, "interaction.json"),
      recipients,
      (a) => new ReviewApi(base, secret, a),
      transport,
      base,
      () => now,
    );
  let engine = make();
  t.after(async () => {
    app.dispose();
    await new Promise<void>((r) => server.close(() => r()));
    rmSync(dir, { recursive: true, force: true });
  });
  return {
    api,
    transport,
    base,
    dir,
    get engine() {
      return engine;
    },
    restart() {
      engine = make();
    },
    async tick() {
      now += 4000;
      await engine.tick();
    },
    async input(extra: Partial<Incoming>) {
      await engine.inbound({
        id: String(++seq),
        actor: "101",
        chat: "101",
        message: "in-" + seq,
        ...extra,
      });
    },
    async click(text: string, index = -1) {
      const matches = transport.messages.filter((m) =>
        m.buttons.flat().some((b) => b.text === text),
      );
      const m = index < 0 ? matches.at(index)! : matches[index];
      assert.ok(m, "Button exists: " + text);
      const b = m.buttons.flat().find((b) => b.text === text)!;
      await this.input({ message: m.id, callback: b.callback_data });
    },
    async review(id: string) {
      const c = await api.get("demo_" + id),
        b = engine.binding(c, recipients[0]),
        key = `${b.run}/${b.review}/101/101`;
      const d = {
        ...b,
        key,
        type: "review" as const,
        attempts: 0,
        due: 0,
        documents: {},
        documentAttempts: 0,
        documentDue: 0,
      };
      engine.state.deliveries[key] = d;
      await engine.deliver(d, c);
      return transport.messages
        .filter((m) => m.buttons.length && m.text.includes(c.email.subject))
        .at(-1)!;
    },
    async advance() {
      await fetch(base + "/api/demo/advance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    },
    async fault(mode: string) {
      await fetch(base + "/api/demo/decision-fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
    },
  };
}
test("Conversational review details are read-only, scoped and leave exact confirmation usable", async (t) => {
  const h = await setup(t),
    mismatch = await h.review("mismatch-review");
  assert.match(mismatch.text, /Could you check the BL gross weight/);
  assert.match(mismatch.text, /container count: SI 3, BL 4/);
  const m = await h.review("grounded-input");
  assert.ok(!m.text.includes("DOCUMENT_EXTRACTED") && !m.text.includes("Run:"));
  await h.input({ reply: m.id, text: "21707" });
  await h.click("View details");
  assert.match(
    h.transport.messages.at(-1)!.text,
    /Frozen machine assessment: NEEDS_REVIEW/,
  );
  assert.match(h.transport.messages.at(-1)!.text, /DOCUMENT_EXTRACTED/);
  await h.click("Open dashboard");
  assert.match(h.transport.messages.at(-1)!.text, /copy it into the browser/);
  let c = await h.api.get("demo_grounded-input");
  assert.equal(c.review?.status, "OPEN");
  assert.equal(
    c.history.filter((e) => e.type === "DECISION_RECEIVED").length,
    0,
  );
  await h.click("Confirm value");
  assert.equal((await h.api.get(c.case_id)).workflow_status, "PROCESSING");
  await h.advance();
  await h.api.request("/cases/" + c.case_id + "/reprocess", {});
  await h.click("View details");
  assert.match(
    h.transport.messages.at(-1)!.text,
    /already been handled or replaced/,
  );
});

test("F2 grounded explicit reply, persisted preview, authenticated callback, 202 and frozen outcome", async (t) => {
  const h = await setup(t),
    before = await h.api.get("demo_grounded-input"),
    m = await h.review("grounded-input");
  assert.ok(h.transport.files.length);
  assert.match(
    Buffer.from(h.transport.files[0].data, "base64").toString(),
    /synthetic/i,
  );
  await h.input({ text: "21707" });
  assert.equal((await h.api.get(before.case_id)).review?.status, "OPEN");
  await h.input({ text: "21707", reply: m.id });
  h.restart();
  await h.click("Confirm value");
  let c = await h.api.get(before.case_id);
  assert.equal(c.workflow_status, "PROCESSING");
  assert.match(h.transport.messages.at(-1)!.text, /202/);
  await h.advance();
  c = await h.api.get(before.case_id);
  assert.equal(c.resolution?.channel, "TELEGRAM");
  assert.equal(c.resolution?.actor_id, "101");
  assert.equal(c.resolution?.final_status, "OK");
  assert.deepEqual(c.machine_assessment, before.machine_assessment);
  await h.input({ text: "/reviews" });
  await h.tick();
  await h.tick();
  const outcomes = () =>
    h.transport.messages.filter(
      (m) =>
        m.text.includes(
          "The check is finished—the compared values now match",
        ) && m.text.includes(before.email.subject),
    );
  assert.equal(
    outcomes().length,
    1,
    "settled outcome must actually be sent to Telegram",
  );
  assert.match(outcomes()[0].text, /original machine assessment is unchanged/);
  h.restart();
  await h.tick();
  assert.equal(
    outcomes().length,
    1,
    "restart must not duplicate delivered outcome",
  );
  await h.click("Confirm value");
  assert.equal(
    (await h.api.get(before.case_id)).history.filter(
      (x) => x.type === "DECISION_RECEIVED",
    ).length,
    1,
  );
});
test("F2 recovers legacy outcome message alias without repeating it after restart", async (t) => {
  const h = await setup(t),
    m = await h.review("grounded-input");
  await h.input({ text: "21707", reply: m.id });
  await h.click("Confirm value");
  await h.advance();
  const p = Object.values(h.engine.state.proposals).find(
    (p) => p.phase === "done",
  )!;
  Object.assign(p, { message: m.id });
  const key = `${p.run}/outcome/${p.review}/${p.actor}/${p.chat}`;
  h.engine.state.deliveries[key] = {
    ...p,
    key,
    type: "outcome",
    message: m.id,
    held: false,
    attempts: 0,
    due: 0,
    documents: {},
    documentAttempts: 0,
    documentDue: 0,
  };
  h.engine.state.recipients = ["101/101"];
  h.engine.save();
  h.restart();
  await h.tick();
  await h.tick();
  const outcomes = () =>
    h.transport.messages.filter(
      (m) =>
        m.text.includes(
          "The check is finished—the compared values now match",
        ) && m.text.includes("Source available"),
    );
  assert.equal(outcomes().length, 1);
  assert.notEqual(outcomes()[0].id, m.id);
  h.restart();
  await h.tick();
  assert.equal(outcomes().length, 1);
});

test("F2 notification sends stop after bounded failures instead of flooding indefinitely", async (t) => {
  const h = await setup(t),
    api = new ReviewApi(h.base, secret, "101");
  const listed = await api.list();
  let arrived = false;
  api.list = async () =>
    arrived ? listed.filter((c) => c.case_id === "demo_grounded-input") : [];
  let now = 100000;
  const engine = new ReviewEngine(
    join(h.dir, "bounded.json"),
    [{ actor: "101", chat: "101" }],
    () => api,
    h.transport,
    h.base,
    () => now,
  );
  await engine.inbound({
    id: "start",
    actor: "101",
    chat: "101",
    message: "1",
    text: "/start",
  });
  await engine.tick();
  arrived = true;
  const before = h.transport.sendAttempts;
  h.transport.failSend = true;
  for (let i = 0; i < 8; i++) {
    now += 60001;
    await engine.tick();
  }
  assert.equal(h.transport.sendAttempts - before, 5);
  assert.equal(
    (await api.get("demo_grounded-input")).review?.notified_at,
    null,
  );
});
test("F2 unsupported value, cancel/edit invalidates exact override; persisted human evidence", async (t) => {
  const h = await setup(t),
    m = await h.review("field-input");
  await h.input({ reply: m.id, text: "22000" });
  await h.click("Confirm value");
  assert.equal((await h.api.get("demo_field-input")).review?.status, "OPEN");
  const old = h.transport.messages.at(-1)!;
  await h.input({ reply: m.id, text: "23000" });
  await h.input({ message: old.id, callback: old.buttons[0][0].callback_data });
  assert.equal((await h.api.get("demo_field-input")).review?.status, "OPEN");
  await h.click("Confirm value");
  h.restart();
  await h.click("Confirm exact override");
  await h.advance();
  const c = await h.api.get("demo_field-input"),
    v = c.fields.find((f) => f.field === "gross_weight_kg")!.bl!;
  assert.equal(v.normalized, 23000);
  assert.equal(v.grounded, false);
  assert.equal(v.value_origin, "MANUAL_OVERRIDE");
  assert.equal(c.follow_up, "CORRECTION_REQUIRED");
  const p = Object.values(h.engine.state.proposals).find(
    (p) => p.phase === "done",
  )!;
  assert.equal(p.confirmation?.actor, "101");
  assert.equal(
    p.decision.action === "PROVIDE_VALUE" &&
      p.decision.override_confirmation?.proposed_value,
    23000,
  );
});
test("F2 choices, document-role targeting, unsupported candidate and all escapes", async (t) => {
  for (const id of [
    "candidate-choice",
    "document-choice",
    "unsupported-candidate",
    "blocked-open",
    "field-input",
  ]) {
    const h = await setup(t),
      m = await h.review(id),
      before = await h.api.get("demo_" + id);
    const isCandidate = id === "unsupported-candidate";
    if (isCandidate) {
      const opt = before.review!.options!.find(
        (o) => o.kind === "VALUE" && o.value.normalized === 23000,
      )!;
      await h.click(opt.label);
      await h.click("Confirm exact override");
    } else if (id === "document-choice" || id === "candidate-choice") {
      const opt = before.review!.options!.find((o) => o.kind !== "ESCAPE")!;
      await h.click(opt.label);
    } else await h.click(m.buttons[0][0].text);
    await h.advance();
    const c = await h.api.get(before.case_id);
    assert.notEqual(c.review?.status, "OPEN");
    assert.deepEqual(c.machine_assessment, before.machine_assessment);
    if (["blocked-open", "field-input"].includes(id))
      assert.equal(c.workflow_status, "BLOCKED_EXTERNAL");
  }
  const h = await setup(t),
    m = await h.review("candidate-choice");
  const c = await h.api.get("demo_candidate-choice");
  await h.click(
    c.review!.options!.find((o) => o.option_id === "NONE_OF_THESE")!.label,
  );
  await h.advance();
  assert.equal(
    (await h.api.get(c.case_id)).workflow_status,
    "BLOCKED_EXTERNAL",
  );
});
test("F2 SI before BL; old replies and reprocessed callbacks never migrate", async (t) => {
  const h = await setup(t),
    m = await h.review("both-sides");
  assert.match(m.text, /SI gross weight/);
  await h.input({ reply: m.id, text: "21707" });
  await h.click("Confirm value");
  await h.advance();
  let c = await h.api.get("demo_both-sides");
  assert.equal(c.review?.side, "BL");
  await h.input({ reply: m.id, text: "22000" });
  assert.equal((await h.api.get(c.case_id)).review?.status, "OPEN");
  const second = await h.review("both-sides");
  await h.input({ reply: second.id, text: "21707" });
  const proposal = h.transport.messages.at(-1)!;
  await h.api.request("/cases/" + c.case_id + "/reprocess", {});
  await h.input({
    message: proposal.id,
    callback: proposal.buttons[0][0].callback_data,
  });
  c = await h.api.get(c.case_id);
  assert.equal(c.workflow_status, "PROCESSING");
  assert.equal(c.resolution, null);
});
test("F2 dashboard race and duplicate update accept one decision only", async (t) => {
  const h = await setup(t),
    m = await h.review("grounded-input");
  await h.input({ reply: m.id, text: "21707" });
  const p = h.transport.messages.at(-1)!,
    c = await h.api.get("demo_grounded-input");
  const dashboard = fetch(
    h.base + "/api/v1/reviews/" + c.review!.review_id + "/decision",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review_id: c.review!.review_id,
        run_id: c.run.run_id,
        channel: "DASHBOARD",
        actor_id: "demo-guest",
        action: "PROVIDE_VALUE",
        field: "gross_weight_kg",
        side: "BL",
        value: 21707,
      }),
    },
  );
  await Promise.all([
    dashboard,
    h.input({
      id: "duplicate",
      message: p.id,
      callback: p.buttons[0][0].callback_data,
    }),
    h.input({
      id: "duplicate",
      message: p.id,
      callback: p.buttons[0][0].callback_data,
    }),
  ]);
  assert.equal(
    (await h.api.get(c.case_id)).history.filter(
      (x) => x.type === "DECISION_RECEIVED",
    ).length,
    1,
  );
});
test("F2 lost acceptance and resumption failure preserve decision, no automatic resubmission", async (t) => {
  const h = await setup(t),
    m = await h.review("grounded-input");
  await h.input({ reply: m.id, text: "21707" });
  await h.fault("lost-response");
  await h.click("Confirm value");
  h.restart();
  await h.advance();
  await h.tick();
  const c = await h.api.get("demo_grounded-input");
  assert.equal(
    c.history.filter((x) => x.type === "DECISION_RECEIVED").length,
    1,
  );
  assert.equal(c.workflow_status, "COMPLETED");
  const other = await h.review("resume-failure");
  await h.input({ reply: other.id, text: "22000" });
  await h.click("Confirm value");
  await h.click("Confirm exact override");
  await h.advance();
  assert.equal(
    (await h.api.get("demo_resume-failure")).workflow_status,
    "FAILED",
  );
});
test("F2 send-marker recovery, document failure, persisted dedup, flood and digest isolation", async (t) => {
  const h = await setup(t);
  await h.input({ text: "/start" });
  h.transport.failDocuments = true;
  await h.tick();
  const sent = h.transport.messages.filter((m) => m.buttons.length);
  assert.equal(sent.length, 1);
  assert.ok(h.transport.messages.some((m) => m.text.includes("queued")));
  let cases = await h.api.list(),
    notified = 0;
  for (const s of cases)
    if ((await h.api.get(s.case_id)).review?.notified_at) notified++;
  assert.ok(
    notified < cases.filter((s) => s.has_open_review).length,
    "digest does not mark individual reviews",
  );
  const before = h.transport.messages.length;
  h.restart();
  await h.engine.tick();
  assert.equal(
    h.transport.messages.length,
    before,
    "restart does not resend review or unchanged digest",
  );
  for (let i = 0; i < 20; i++) await h.tick();
  assert.equal(
    h.transport.messages.length,
    before,
    "A static backlog must not drain into chat, even after a minute",
  );
  assert.equal(
    h.transport.files.length,
    0,
    "Digest cannot send source documents",
  );
  assert.equal(
    (await h.api.get("demo_grounded-input")).review?.notified_at,
    null,
  );
  await h.click(
    "Quick review · Confirm BL value · Source available · enter BL gross weight",
  );
  assert.ok(
    h.transport.messages.some((m) =>
      m.text.includes("couldn’t attach the source document"),
    ),
  );
  h.transport.failDocuments = false;
  await h.tick();
  await h.tick();
  assert.ok(h.transport.files.length > 0);
  await h.input({ text: "/pause" });
  const pausedCount = h.transport.messages.length;
  h.restart();
  await h.tick();
  assert.equal(
    h.transport.messages.length,
    pausedCount,
    "Pause survives restart and stops proactive delivery",
  );
});
test("F2 unauthorized sender/chat, service spoof, EVAL and cross-scope documents denied", async (t) => {
  const h = await setup(t),
    m = await h.review("grounded-input");
  const n = h.transport.messages.length;
  await h.input({ actor: "999", reply: m.id, text: "21707" });
  await h.input({ chat: "999", reply: m.id, text: "21707" });
  assert.equal(h.transport.messages.length, n);
  await assert.rejects(
    new ReviewApi(h.base, "bad", "101").list(),
    (e: unknown) => e instanceof RemoteError && e.status === 401,
  );
  await assert.rejects(
    new ReviewApi(h.base, secret, "999").list(),
    (e: unknown) => e instanceof RemoteError && e.status === 403,
  );
  await assert.rejects(
    h.api.request("/cases?run_kind=EVAL"),
    (e: unknown) => e instanceof RemoteError && e.status === 403,
  );
  await assert.rejects(h.api.get("eval_secret"));
  const c = await h.api.get("demo_grounded-input");
  await assert.rejects(h.api.document(c, "eval_secret"));
  await assert.rejects(h.api.request("/documents/eval_secret/content"));
  const r = await fetch(
    h.base + "/api/v1/reviews/" + c.review!.review_id + "/notified",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: c.run.run_id }),
    },
  );
  assert.equal(r.status, 403);
});
test("F2 successful send with failed notified marker resumes marker only after restart", async (t) => {
  const h = await setup(t);
  let fail = true;
  const api = new ReviewApi(h.base, secret, "101"),
    original = api.notified.bind(api);
  api.notified = async (r, run) => {
    if (fail) throw new Error("Injected marker outage");
    return original(r, run);
  };
  const path = join(h.dir, "marker.json"),
    recipients = [{ actor: "101", chat: "101" }];
  let engine = new ReviewEngine(
    path,
    recipients,
    () => api,
    h.transport,
    h.base,
    () => 100000,
  );
  const c = await api.get("demo_grounded-input"),
    b = engine.binding(c, recipients[0]),
    d = {
      ...b,
      key: "delivery",
      message: undefined as string | undefined,
      type: "review" as const,
      attempts: 0,
      due: 0,
      documents: {},
      documentAttempts: 0,
      documentDue: 0,
    };
  engine.state.deliveries.delivery = d;
  await assert.rejects(engine.deliver(d, c));
  assert.ok(d.message);
  assert.equal((await api.get(c.case_id)).review?.notified_at, null);
  const count = h.transport.messages.length;
  fail = false;
  engine = new ReviewEngine(path, recipients, () => api, h.transport, h.base);
  await engine.deliver(
    engine.state.deliveries.delivery,
    await api.get(c.case_id),
  );
  assert.equal(h.transport.messages.length, count);
  assert.ok((await api.get(c.case_id)).review?.notified_at);
  assert.equal(
    (await api.get(c.case_id)).history.filter(
      (h) => h.type === "REVIEW_NOTIFIED",
    ).length,
    1,
  );
});
test("F2 two sequential reviews complete; wrong actor callback, cancellation and malformed input cannot submit", async (t) => {
  const h = await setup(t),
    first = await h.review("both-sides");
  await h.input({ reply: first.id, text: "1,234" });
  assert.match(h.transport.messages.at(-1)!.text, /without grouping/);
  await h.input({ reply: first.id, text: "21707" });
  const p = h.transport.messages.at(-1)!;
  await h.input({
    actor: "202",
    chat: "202",
    message: p.id,
    callback: p.buttons[0][0].callback_data,
  });
  assert.equal((await h.api.get("demo_both-sides")).review?.status, "OPEN");
  await h.click("Cancel");
  await h.input({ message: p.id, callback: p.buttons[0][0].callback_data });
  assert.equal((await h.api.get("demo_both-sides")).review?.status, "OPEN");
  await h.input({ reply: first.id, text: "21707" });
  await h.click("Confirm value");
  await h.advance();
  const second = await h.review("both-sides");
  assert.match(second.text, /BL gross weight/);
  await h.input({ reply: second.id, text: "21707" });
  await h.click("Confirm value");
  await h.advance();
  const c = await h.api.get("demo_both-sides");
  assert.equal(c.workflow_status, "COMPLETED");
  assert.equal(c.resolution?.final_status, "OK");
  assert.equal(
    c.history.filter((h) => h.type === "DECISION_RECEIVED").length,
    2,
  );
});
test("F2 notifier correction and operator-only failure, active-run queued recheck and bounded send retries", async (t) => {
  const h = await setup(t);
  await h.input({ text: "/start" });
  await h.input({ actor: "202", chat: "202", text: "/start" });
  await h.tick();
  const business = h.transport.messages.find(
    (m) => m.chat === "101" && m.buttons.length,
  )!;
  assert.ok(
    business.buttons
      .flat()
      .every(
        (b) =>
          !b.text.startsWith(
            "Needs investigation · Resolve processing failure",
          ),
      ),
  );
  const mismatch = business.buttons
    .flat()
    .find(
      (b) =>
        b.text ===
        "Needs investigation · Check corrections needed · Container quantity differs",
    )!;
  await h.input({ message: business.id, callback: mismatch.callback_data });
  const operator = h.transport.messages.find(
    (m) => m.chat === "202" && m.buttons.length,
  )!;
  const failure = operator.buttons
    .flat()
    .find((b) =>
      b.text.startsWith("Needs investigation · Resolve processing failure"),
    )!;
  await h.input({
    actor: "202",
    chat: "202",
    message: operator.id,
    callback: failure.callback_data,
  });
  assert.ok(
    h.transport.messages.some(
      (m) =>
        m.text.includes("corrections are still needed") &&
        m.buttons
          .flat()
          .every((b) => ["View details", "Open dashboard"].includes(b.text)),
    ),
  );
  const failures = h.transport.messages.filter((m) =>
    m.text.includes("operator help needed"),
  );
  assert.ok(failures.length);
  assert.ok(failures.every((m) => m.chat === "202"));
  const old = await h.api.get("demo_grounded-input");
  const oldButton = business.buttons
    .flat()
    .find(
      (b) =>
        b.text ===
        "Quick review · Confirm BL value · Source available · enter BL gross weight",
    )!;
  await h.api.request("/cases/" + old.case_id + "/reprocess", {});
  const n = h.transport.messages.length;
  await h.input({ message: business.id, callback: oldButton.callback_data });
  assert.match(
    h.transport.messages.at(-1)!.text,
    /already been handled or replaced/,
  );
  await h.tick();
  assert.ok(
    h.transport.messages
      .slice(n)
      .every((m) => !m.text.includes(old.run.run_id)),
  );
});

test("Consumed confirmations disappear, retain navigation, and retry edits without repeating decisions", async (t) => {
  const h = await setup(t);
  const review = await h.review("grounded-input");
  await h.input({ reply: review.id, text: "21707" });
  const preview = h.transport.messages.at(-1)!;
  await h.click("Cancel");
  const cancelled = h.transport.edits.find((e) => e.message === preview.id)!;
  assert.match(cancelled.text!, /closed/);
  assert.deepEqual(
    cancelled.buttons.flat().map((b) => b.text),
    ["View details", "Open dashboard"],
  );
  assert.ok(
    !h.transport.edits.some((e) => e.message === review.id),
    "Cancel keeps the original review usable",
  );
  await h.input({ reply: review.id, text: "21707" });
  const next = h.transport.messages.at(-1)!;
  h.transport.failEdit = true;
  await h.click("Confirm value");
  assert.equal(
    (await h.api.get("demo_grounded-input")).history.filter(
      (e) => e.type === "DECISION_RECEIVED",
    ).length,
    1,
  );
  h.restart();
  h.transport.failEdit = false;
  await h.tick();
  const submitted = h.transport.edits.find((e) => e.message === next.id)!;
  assert.match(submitted.text!, /Submitted/);
  assert.deepEqual(
    submitted.buttons.flat().map((b) => b.text),
    ["View details", "Open dashboard"],
  );
  assert.ok(h.transport.edits.some((e) => e.message === review.id));
  const old = next.buttons.flat().find((b) => b.text === "Confirm value")!;
  await h.input({ message: next.id, callback: old.callback_data });
  assert.equal(
    (await h.api.get("demo_grounded-input")).history.filter(
      (e) => e.type === "DECISION_RECEIVED",
    ).length,
    1,
  );
});

test("Telegram queue puts evidenced quick reviews before investigation without hiding any cases", async (t) => {
  const h = await setup(t);
  await h.input({ text: "/reviews" });
  await h.tick();
  const queue = h.transport.messages.find(
    (m) => m.chat === "101" && m.buttons.length,
  )!;
  const buttons = queue.buttons.flat().filter(b => h.engine.state.buttons[b.callback_data.slice(5)].action === "show");
  let page = queue;
  while (page.buttons.flat().some(b => b.text === "Next →")) {
    await h.click("Next →");
    page = h.transport.messages.at(-1)!;
    buttons.push(...page.buttons.flat().filter(b => h.engine.state.buttons[b.callback_data.slice(5)].action === "show"));
  }
  const labels = buttons.map((b) => b.text);
  assert.ok(labels[0].startsWith("Quick review"));
  const firstInvestigation = labels.findIndex((l) =>
    l.startsWith("Needs investigation"),
  );
  assert.ok(firstInvestigation > 0);
  assert.ok(
    labels
      .slice(firstInvestigation)
      .every((l) => !l.startsWith("Quick review")),
  );
  const ids = buttons.map(
    (b) => h.engine.state.buttons[b.callback_data.slice(5)].binding.caseId,
  );
  assert.ok(ids.includes("demo_grounded-input"));
  assert.ok(ids.includes("demo_field-input"));
  assert.ok(ids.includes("demo_blocked-open"));
  assert.equal(new Set(ids).size, ids.length);
});

test("Full inbox queue stays bounded, reaches every case, and retries a failed digest after restart", async (t) => {
  const dataset = Array.from({length:520}, (_, i) => ({email_id:`email_${i}`, from:"sender@example.test", subject:"Long source subject ".repeat(8), body:"Practice source", attachments:i < 126 ? ["SI.txt","BL.txt"] : []}));
  const h = await setup(t, dataset);
  await h.input({text:"/reviews"});
  h.transport.failSend = true;
  await assert.rejects(h.tick(), /Injected send failure/);
  assert.equal(h.engine.state.digests["101/101"], undefined);
  assert.ok(h.engine.state.digestRequested?.includes("101/101"));
  h.restart();
  h.transport.failSend = false;
  await h.tick();
  assert.ok(h.engine.state.digests["101/101"]);
  const expected = (await h.api.list()).filter(c => c.has_open_review || c.final_status === "MISMATCH").map(c => c.case_id);
  assert.ok(expected.length > 50);
  const seen: string[] = [];
  let page = h.transport.messages.at(-1)!;
  let selected: {message:string; callback:string} | undefined;
  for (;;) {
    const buttons = page.buttons.flat();
    assert.ok(buttons.length <= 12);
    assert.ok(Buffer.byteLength(JSON.stringify({inline_keyboard:page.buttons})) < 4000);
    for (const button of buttons) {
      const stored = h.engine.state.buttons[button.callback_data.slice(5)];
      if (stored.action !== "show") continue;
      seen.push(stored.binding.caseId);
      if (stored.binding.review) selected = {message:page.id,callback:button.callback_data};
    }
    if (!buttons.some(b => b.text === "Next →")) break;
    h.restart();
    await h.click("Next →");
    page = h.transport.messages.at(-1)!;
  }
  assert.deepEqual([...seen].sort(), expected.sort());
  assert.equal(new Set(seen).size, seen.length);
  assert.ok(selected);
  await h.input(selected);
  assert.ok(h.transport.files.length > 0, "Selected review delivers source documents");
  assert.ok(h.transport.messages.at(-1)!.buttons.length > 0, "Selected review has action buttons");
});
