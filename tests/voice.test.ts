import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHmac } from "node:crypto";
import type { AddressInfo } from "node:net";
import { createApp } from "../server/app";
import { DemoStore } from "../server/store";
import { ReviewApi } from "../interaction/api";
import { ReviewEngine } from "../interaction/engine";
import { VoiceService } from "../interaction/voice";
import {
  TwilioProvider,
  VoiceProviderError,
  type VoiceProvider,
  type VoiceReply,
} from "../interaction/voice-provider";
import { voiceApp } from "../interaction/voice-http";

const token = "voice-test-distinct-credential-000000000",
  telegram = "telegram-test-credential-000000000000000";
async function harness(t: TestContext, demoHandset = false) {
  const dir = mkdtempSync(join(tmpdir(), "voice-v1-"));
  const app = createApp({
    stateFile: join(dir, "simulator.json"),
    interaction: { token: telegram, actors: ["101"] },
    voice: { token, actors: ["101"] },
  });
  const server = app.app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const api = new ReviewApi(base, token, "101", "VOICE"),
    normal = new ReviewApi(base, telegram, "101");
  const sent: string[] = [],
    documents: string[] = [],
    calls: string[] = [],
    ended: string[] = [];
  let failEvidence = false,
    now = Date.parse("2026-09-20T04:00:00Z"),
    sequence = 0;
  const provider: VoiceProvider = {
    applicationDeadlineOnly: demoHandset,
    async start(phone) {
      calls.push(phone);
      return "CAout";
    },
    async end(call) {
      ended.push(call);
    },
    async limit() {},
    validate() {
      return true;
    },
    render(r) {
      return r.text;
    },
  };
  const engine = new ReviewEngine(
    join(dir, "telegram.json"),
    [{ actor: "101", chat: "101" }],
    () => normal,
    {
      async send(_chat, text) {
        sent.push(text);
        return String(sent.length);
      },
      async document(_chat, file) {
        if (failEvidence) throw new Error("Offline");
        documents.push(file.filename);
        return "doc";
      },
    },
    base,
    () => now,
  );
  const enrollment = [
    {
      actor: "101",
      phone: "+60123456789",
      optedIn: false,
      outboundCaseId: "demo_candidate-choice",
    },
  ];
  const make = () =>
    new VoiceService(
      join(dir, "voice.json"),
      engine,
      () => api,
      provider,
      enrollment,
      () => now,
      demoHandset ? 600 : 90,
      { start: 22, end: 8 },
      demoHandset,
    );
  let voice = make(),
    session = "",
    call = "CAin",
    reply: VoiceReply;
  t.after(async () => {
    app.dispose();
    await new Promise<void>((r) => server.close(() => r()));
    rmSync(dir, { recursive: true, force: true });
  });
  const h = {
    api,
    normal,
    base,
    sent,
    documents,
    enrollment,
    calls,
    ended,
    provider,
    engine,
    get voice() {
      return voice;
    },
    get session() {
      return session;
    },
    get reply() {
      return reply;
    },
    state() {
      return voice.state.sessions[session];
    },
    restart() {
      voice = make();
    },
    advanceTime(ms: number) {
      now += ms;
    },
    failEvidence() {
      failEvidence = true;
    },
    async advance() {
      await fetch(base + "/api/demo/advance", { method: "POST" });
    },
    async start() {
      const r = await voice.start(call, enrollment[0].phone);
      assert("session" in r);
      session = r.session;
      reply = r;
      return r;
    },
    async startOutbound() {
      engine.state.recipients = ["101/101"];
      enrollment[0].optedIn = true;
      await voice.tick();
      const s = Object.values(voice.state.sessions).at(-1)!;
      session = s.id;
      call = s.call!;
      reply = await voice.start(call, enrollment[0].phone, session);
      return reply;
    },
    async say(text: string, turn = reply.turn) {
      reply = await voice.turn(session, call, turn, text);
      return reply;
    },
    async authenticate() {
      const r = await h.start();
      const code = r.text.match(/then ([\d ]+) in/)![1].replaceAll(" ", "");
      await voice.approve({
        id: `auth-${++sequence}`,
        actor: "101",
        chat: "101",
        message: "1",
        text: "/voice " + code,
      });
      return h.say("ready");
    },
    async select(caseId = "demo_candidate-choice") {
      await h.authenticate();
      const i = h.state().inbox.findIndex((b) => b.caseId === caseId);
      assert(i >= 0);
      await h.say(`review ${i + 1}`);
      await h.say("I have checked");
    },
  };
  return h;
}

test("complete inbound call authenticates, inspects evidence, confirms VOICE and observes actual simulator resumption", async (t) => {
  const h = await harness(t),
    before = await h.api.get("demo_candidate-choice");
  await h.select();
  assert(h.documents.length > 0);
  assert(h.sent.some((s) => s.includes('"kind":"text_range"')));
  await h.say("option A");
  assert.match(h.reply.text, /21707 kilograms/);
  const confirmationTurn = h.reply.turn;
  await h.say("yes");
  assert.match(h.reply.text, /accepted.*simulator/);
  await h.voice.turn(h.session, "CAin", confirmationTurn, "yes");
  await h.advance();
  await h.say("status");
  const after = await h.api.get(before.case_id);
  assert.equal(after.schema_version, "2.1.2");
  assert.equal(after.resolution?.channel, "VOICE");
  assert.equal(after.resolution?.actor_id, "101");
  assert.equal(after.workflow_status, "COMPLETED");
  assert.deepEqual(after.machine_assessment, before.machine_assessment);
  assert.equal(
    after.history.filter((e) => e.type === "DECISION_RECEIVED").length,
    1,
  );
  assert.equal(after.review?.notified_at, null);
  assert.match(h.reply.text, /check is finished/);
});

test("caller ID and speech cannot authenticate; wrong actor/chat cannot approve", async (t) => {
  const h = await harness(t);
  const start = await h.start();
  assert.doesNotMatch(start.text, /gross|candidate|weight/i);
  const code = start.text.match(/then ([\d ]+) in/)![1].replaceAll(" ", "");
  await h.voice.approve({
    id: "bad",
    actor: "101",
    chat: "other",
    message: "1",
    text: "/voice " + code,
  });
  await h.say("yes");
  assert.equal(h.state().authenticated, false);
  assert.equal(h.state().inbox.length, 0);
  await assert.rejects(() => h.voice.start("CAspoof", "+60999999999"));
});

for (const input of [
  "",
  "no",
  "not now",
  "I cannot tell",
  "option A or B",
  "yes but no",
]) {
  test(`unsafe reply ${JSON.stringify(input)} cannot confirm and a later yes cannot reuse the proposal`, async (t) => {
    const h = await harness(t);
    await h.select();
    await h.say("A");
    await h.say(input);
    await h.say("yes");
    const c = await h.api.get("demo_candidate-choice");
    assert.equal(c.review?.status, "OPEN");
    assert.equal(
      c.history.filter((e) => e.type === "DECISION_RECEIVED").length,
      0,
    );
  });
}
test("unbound yes, inspection bypass, changed option, expiry and disconnect never reuse confirmation", async (t) => {
  const h = await harness(t);
  await h.authenticate();
  await h.say("yes");
  await h.say("review 1");
  await h.say("A");
  assert.equal(h.state().phase, "evidence");
  await h.say("I have checked");
  await h.say("A");
  const old = h.reply.turn;
  await h.say("B");
  assert.match(h.reply.text, /22000 kilograms/);
  h.advanceTime(31000);
  await h.say("yes");
  assert.equal(h.state().proposal, undefined);
  await h.say("A");
  await h.voice.disconnect("CAin");
  await h.say("yes");
  await h.voice.turn(h.session, "CAin", old, "yes");
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});
test("new run and concurrent Telegram decision invalidate a voice proposal", async (t) => {
  const h = await harness(t);
  await h.select();
  await h.say("A");
  const c = await h.api.get("demo_candidate-choice");
  await h.normal.decide({
    actor_id: "101",
    channel: "TELEGRAM",
    review_id: c.review!.review_id,
    run_id: c.run.run_id,
    action: "SELECT_OPTION",
    option_id: "weight-21707",
  });
  await h.say("yes");
  assert.match(h.reply.text, /handled or replaced/);
  await h.advance();
  assert.equal((await h.api.get(c.case_id)).resolution?.channel, "TELEGRAM");
});
test("superseded run cannot receive the old confirmed option", async (t) => {
  const h = await harness(t);
  await h.select();
  await h.say("A");
  await h.normal.request("/cases/demo_candidate-choice/reprocess", {});
  await h.advance();
  await h.say("yes");
  assert.match(h.reply.text, /handled or replaced/);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});
test("unsupported candidate requires a fresh exact override confirmation and remains ungrounded", async (t) => {
  const h = await harness(t);
  await h.select("demo_unsupported-candidate");
  await h.say("B");
  await h.say("yes");
  assert.match(h.reply.text, /ungrounded manual override/);
  assert.equal(h.state().phase, "override");
  assert.equal(
    (await h.api.get("demo_unsupported-candidate")).review?.status,
    "OPEN",
  );
  await h.say("yes");
  await h.advance();
  const c = await h.api.get("demo_unsupported-candidate");
  assert.equal(c.resolution?.value_source, "MANUAL_OVERRIDE");
  const v = c.fields.find((f) => f.field === "gross_weight_kg")!.bl!;
  assert.equal(v.grounded, false);
  assert.equal(v.override_confirmations[0].proposed_value, 23000);
});
test("evidence failure defers and restart discards unconfirmed proposals", async (t) => {
  const h = await harness(t);
  h.failEvidence();
  await h.authenticate();
  await h.say("review 1");
  assert.equal(h.reply.end, true);
  assert.equal(h.state().proposal, undefined);
  h.restart();
  assert.equal(h.state().phase, "ended");
});
test("declining evidence inspection cannot skip straight to a spoken choice", async (t) => {
  const h = await harness(t);
  await h.authenticate();
  await h.say("review 1");
  await h.say("no");
  await h.say("A");
  await h.say("yes");
  assert.equal(h.reply.end, true);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});
test("inbound provider cap must succeed before authentication begins", async (t) => {
  const h = await harness(t);
  h.provider.limit = async () => {
    throw new Error("Provider offline");
  };
  const r = await h.start();
  assert.equal(r.end, true);
  assert.equal(h.state().authenticated, false);
  assert.equal(h.state().phase, "ended");
});
test("outbound uses the identical authenticated decision journey after Telegram already notified", async (t) => {
  const h = await harness(t),
    c = await h.api.get("demo_candidate-choice");
  await h.normal.notified(c.review!.review_id, c.run.run_id);
  h.engine.state.recipients = ["101/101"];
  h.enrollment[0].optedIn = true;
  await h.voice.tick();
  const s = Object.values(h.voice.state.sessions)[0];
  let r = await h.voice.start("CAout", "+10000000000", s.id);
  const code = r.text.match(/then ([\d ]+) in/)![1].replaceAll(" ", "");
  await h.voice.approve({
    id: "out-auth",
    actor: "101",
    chat: "101",
    message: "1",
    text: "/voice " + code,
  });
  for (const text of ["ready", "review 1", "I have checked", "A", "yes"])
    r = await h.voice.turn(s.id, "CAout", r.turn, text);
  assert.match(r.text, /accepted/);
  await h.advance();
  const after = await h.api.get(c.case_id);
  assert.equal(after.resolution?.channel, "VOICE");
  assert.equal(h.calls.length, 1);
  assert(after.review?.notified_at);
});
test("notifier reconciliation does not replace an active call's status prompt", async (t) => {
  const h = await harness(t);
  await h.select();
  await h.say("A");
  await h.say("yes");
  const turn = h.reply.turn;
  await h.voice.tick();
  assert.equal(h.state().turn, turn);
  await h.advance();
  await h.voice.tick();
  await h.say("status", turn);
  assert.match(h.reply.text, /check is finished/);
});
test("lost HTTP acceptance response reconciles without resubmission across restart", async (t) => {
  const h = await harness(t);
  await h.select();
  await h.say("A");
  await fetch(h.base + "/api/demo/decision-fault", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "lost-response" }),
  });
  await h.say("yes");
  h.restart();
  await h.advance();
  await h.voice.tick();
  const c = await h.api.get("demo_candidate-choice");
  assert.equal(
    c.history.filter((e) => e.type === "DECISION_RECEIVED").length,
    1,
  );
  assert(h.sent.some((s) => s.includes("check is finished")));
});
test("restart before confirmation discards proposal and replayed callback cannot submit", async (t) => {
  const h = await harness(t);
  await h.select();
  await h.say("A");
  h.restart();
  await h.say("yes");
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});
test("attention honors opt-in, quiet hours, one attempt and call cap with Telegram notification semantics intact", async (t) => {
  const h = await harness(t);
  h.engine.state.recipients = ["101/101"];
  await h.voice.tick();
  assert.equal(h.calls.length, 0);
  h.enrollment[0].optedIn = true;
  h.advanceTime(12 * 3600000);
  await h.voice.tick();
  assert.equal(h.calls.length, 0);
  h.advanceTime(12 * 3600000);
  await h.voice.tick();
  assert.equal(h.calls.length, 1);
  const s = Object.values(h.voice.state.sessions)[0];
  await h.voice.start("CAout", "+10000000000", s.id);
  h.advanceTime(91000);
  await h.voice.tick();
  await h.voice.tick();
  assert.deepEqual(h.ended, ["CAout"]);
  assert.equal(h.calls.length, 1);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.notified_at,
    null,
  );
});
test("scoped voice credentials reject actor/channel spoofing, EVAL and notified writes", async (t) => {
  const h = await harness(t),
    c = await h.api.get("demo_candidate-choice");
  await assert.rejects(() =>
    new ReviewApi(h.base, telegram, "101", "VOICE").list(),
  );
  await assert.rejects(() =>
    new ReviewApi(h.base, token, "private", "VOICE").list(),
  );
  await assert.rejects(() => h.api.request("/cases?run_kind=EVAL"));
  await assert.rejects(() => h.api.notified(c.review!.review_id, c.run.run_id));
  await assert.rejects(() =>
    h.api.decide({
      actor_id: "101",
      channel: "TELEGRAM",
      review_id: c.review!.review_id,
      run_id: c.run.run_id,
      action: "SELECT_OPTION",
      option_id: "weight-21707",
    }),
  );
});
test("Twilio signature validation uses exact public URL and all form fields; XML safely escapes content", async (t) => {
  const h = await harness(t),
    p = new TwilioProvider(
      "ACtest",
      "provider-secret",
      "+10000000000",
      "https://voice.example",
    );
  const fields = {
    CallSid: "CAsigned",
    From: "+60123456789",
    Extra: "included",
  };
  const url = "https://voice.example/voice/start";
  const signature = createHmac("sha1", "provider-secret")
    .update(
      url +
        Object.keys(fields)
          .sort()
          .map((k) => k + fields[k as keyof typeof fields])
          .join(""),
    )
    .digest("base64");
  assert(p.validate(url, fields, signature));
  assert.equal(p.validate(url, fields, "é".repeat(signature.length)), false);
  assert(!p.validate(url + "?x=1", fields, signature));
  const app = voiceApp(h.voice, p, "https://voice.example"),
    server = app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  t.after(() => server.close());
  const local = `http://127.0.0.1:${(server.address() as AddressInfo).port}/voice/start`;
  const post = (sig: string) =>
    fetch(local, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Twilio-Signature": sig,
      },
      body: new URLSearchParams(fields),
    });
  assert.equal((await post("forged")).status, 403);
  assert.match(await (await post(signature)).text(), /authenticate/);
  assert.match(
    p.render({ text: '<script>&"', turn: "x" }, "s"),
    /&lt;script&gt;&amp;&quot;/,
  );
  assert.doesNotMatch(
    p.render({ text: "done", turn: "x", end: true }, "s"),
    /Gather/,
  );
});

test("v2.1.1 current simulator migration preserves history and provenance; private legacy data is rejected", () => {
  const store = new DemoStore(),
    saved = store.snapshot();
  for (const [, c] of saved.cases)
    (c as unknown as { schema_version: string }).schema_version = "2.1.1";
  const frozen = structuredClone(saved);
  const restored = new DemoStore();
  restored.restore(saved);
  for (const [id, before] of frozen.cases) {
    const after = restored.get(id);
    assert.equal(after.schema_version, "2.1.2");
    assert.deepEqual(after, { ...before, schema_version: "2.1.2" });
  }
  assert.deepEqual(saved, frozen);
  saved.cases[0][1].run.kind = "EVAL";
  assert.throws(() => restored.restore(saved));
});

test("trial call creation omits restricted parameters; standard creation retains its provider cap", async (t) => {
  const sent: URLSearchParams[] = [];
  t.mock.method(
    globalThis,
    "fetch",
    async (_url: unknown, init: RequestInit) => {
      sent.push(new URLSearchParams(init.body as URLSearchParams));
      return new Response(JSON.stringify({ sid: "CA" + "a".repeat(32) }), {
        status: 201,
      });
    },
  );
  await new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
    "trial",
  ).start("+60123456789", "session", 180);
  assert.deepEqual([...sent[0].keys()].sort(), [
    "From",
    "StatusCallback",
    "To",
    "Url",
  ]);
  await new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
  ).start("+60123456789", "session", 180);
  assert.equal(sent[1].get("TimeLimit"), "180");
});

test("provider rejection preserves safe status/code without phone numbers, tokens or response messages", async (t) => {
  t.mock.method(
    globalThis,
    "fetch",
    async () =>
      new Response(
        JSON.stringify({
          code: 0,
          message:
            "Invalid or disallowed parameters provided - trial accounts have limited parameter access; private token and phone",
        }),
        { status: 400 },
      ),
  );
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
  );
  await assert.rejects(
    () => p.start("+60123456789", "session", 180),
    (error: unknown) => {
      assert(error instanceof VoiceProviderError);
      assert.deepEqual(error.diagnostic, {
        kind: "http",
        httpStatus: 400,
        providerCode: 0,
        trialParameterRestriction: true,
      });
      assert.doesNotMatch(
        JSON.stringify(error),
        /private token|60123456789|secret/,
      );
      return true;
    },
  );
});

test("outbound duration failure saves the call ID, attempts hangup and never authenticates or redials", async (t) => {
  const h = await harness(t);
  h.engine.state.recipients = ["101/101"];
  h.enrollment[0].optedIn = true;
  h.provider.limit = async () => {
    throw new VoiceProviderError({
      kind: "http",
      httpStatus: 400,
      providerCode: 0,
    });
  };
  await h.voice.tick();
  const s = Object.values(h.voice.state.sessions)[0];
  assert.equal(s.call, "CAout");
  assert.equal(s.phase, "ended");
  assert.equal(s.authenticated, false);
  assert.equal(s.providerFailure?.stage, "limit");
  assert.deepEqual(h.ended, ["CAout"]);
  h.restart();
  await h.voice.tick();
  assert.equal(h.calls.length, 1);
  const r = await h.voice.start("CAout", "+10000000000", s.id);
  assert.equal(r.end, true);
});

test("creation failure diagnostics survive restart and keep the one-attempt guard", async (t) => {
  const h = await harness(t);
  h.engine.state.recipients = ["101/101"];
  h.enrollment[0].optedIn = true;
  let count = 0;
  h.provider.start = async () => {
    count++;
    throw new VoiceProviderError({
      kind: "http",
      httpStatus: 400,
      providerCode: 0,
      trialParameterRestriction: true,
    });
  };
  await h.voice.tick();
  h.restart();
  await h.voice.tick();
  const s = Object.values(h.voice.state.sessions)[0];
  assert.equal(count, 1);
  assert.equal(s.providerFailure?.stage, "create");
  assert.equal(s.providerFailure?.diagnostic.trialParameterRestriction, true);
});

test("trial demo HTTP journey uses expiring capabilities, Telegram identity, explicit confirmation and one simulator decision", async (t) => {
  const h = await harness(t);
  const p = new TwilioProvider(
    "ACtest",
    "trial-demo-secret",
    "+10000000000",
    "https://voice.example",
    "trial-demo",
  );
  const originalFetch = globalThis.fetch;
  let startUrl = "",
    creates = 0;
  const call = "CA" + "b".repeat(32);
  t.mock.method(
    globalThis,
    "fetch",
    async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).startsWith("https://api.twilio.com/")) {
        creates++;
        assert(String(input).endsWith("/Calls.json"));
        startUrl = new URLSearchParams(init!.body as URLSearchParams).get(
          "Url",
        )!;
        return new Response(JSON.stringify({ sid: call }), { status: 201 });
      }
      return originalFetch(input, init);
    },
  );
  Object.assign(h.provider, {
    applicationDeadlineOnly: true,
    start: p.start.bind(p),
    limit: p.limit.bind(p),
    end: p.end.bind(p),
  });
  h.engine.state.recipients = ["101/101"];
  h.enrollment[0].optedIn = true;
  await h.voice.tick();
  const session = Object.values(h.voice.state.sessions)[0];
  assert.equal(creates, 1);
  const server = voiceApp(h.voice, p, p.origin).listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  t.after(() => server.close());
  const local = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const post = (
    url: string,
    fields: Record<string, string> = {},
    signature?: string,
  ) =>
    originalFetch(local + new URL(url).pathname + new URL(url).search, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        ...(signature ? { "X-Twilio-Signature": signature } : {}),
      },
      body: new URLSearchParams(fields),
    });
  assert.equal(
    (await post(startUrl.replace(/cap=[^&]+/, "cap=forged"))).status,
    403,
  );
  assert.equal((await post(startUrl, { CallSid: "CAwrong" })).status, 403);
  assert.equal((await post(startUrl, {}, "invalid-signature")).status, 403);
  const reply = await (await post(startUrl)).text();
  assert.match(reply, /authenticate/);
  assert.doesNotMatch(reply, /21707|Gross weight/);
  const action = (xml: string) =>
    / action="([^"]+)"/.exec(xml)![1].replaceAll("&amp;", "&");
  const code = session
    .authPrompt!.match(/then ([\d ]+) in/)![1]
    .replaceAll(" ", "");
  assert.equal((reply.match(/<Pause length="1"\/>/g) ?? []).length, 12);
  await h.voice.approve({
    id: "trial-auth",
    actor: "101",
    chat: "101",
    message: "1",
    text: "/voice " + code,
  });
  const say = async (xml: string, speech: string) => {
    const r = await post(action(xml), { SpeechResult: speech });
    assert.equal(r.status, 200);
    return r.text();
  };
  let xml = await say(reply, "ready");
  const index = session.inbox.findIndex(
    (b) => b.caseId === "demo_candidate-choice",
  );
  xml = await say(xml, `review ${index + 1}`);
  assert(h.documents.length > 0);
  xml = await say(xml, "I have checked");
  xml = await say(xml, "option A");
  assert.match(xml, /21707 kilograms/);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  const confirm = xml;
  xml = await say(xml, "yes");
  assert.match(xml, /accepted by the simulator/);
  const replay = await say(confirm, "option B");
  assert.equal(
    /<Say[^>]*>(.*?)<\/Say>/.exec(replay)![1],
    /<Say[^>]*>(.*?)<\/Say>/.exec(xml)![1],
  );
  assert.equal(
    new URL(action(replay)).searchParams.get("turn"),
    new URL(action(xml)).searchParams.get("turn"),
  );
  await h.advance();
  xml = await say(xml, "status");
  assert.match(xml, /compared values now match/);
  assert.match(xml, /<Hangup/);
  const after = await h.api.get("demo_candidate-choice");
  assert.equal(after.resolution?.channel, "VOICE");
  assert.equal(
    after.history.filter((e) => e.type === "DECISION_RECEIVED").length,
    1,
  );
  assert.equal(
    (
      await post(p.origin + "/voice/status?" + new URL(startUrl).searchParams, {
        CallSid: call,
        CallStatus: "completed",
      })
    ).status,
    403,
  );
  h.advanceTime(181000);
  assert.equal((await post(startUrl)).status, 403);
  await h.voice.tick();
  assert.equal(creates, 1);
});

test("trial capability cannot authorize another endpoint, altered turn, duplicate fields, expired link or standard mode", () => {
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
    "trial-demo",
  );
  const standard = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
  );
  const xml = p.render(
    { text: "prompt", turn: "b".repeat(32) },
    "a".repeat(32),
  );
  const url = / action="([^"]+)"/.exec(xml)![1].replaceAll("&amp;", "&");
  assert(p.validateCapability(url));
  assert(!standard.validateCapability(url));
  assert(!p.validateCapability(url.replace("/voice/turn", "/voice/status")));
  assert(
    !p.validateCapability(
      url.replace("turn=" + "b".repeat(32), "turn=" + "c".repeat(32)),
    ),
  );
  assert(!p.validateCapability(url + "&session=" + "a".repeat(32)));
  assert(!p.validateCapability(url.replace(/expires=\d+/, "expires=1")));
  assert(
    !p.validateCapability(url.replace(/cap=[^&]+/, "cap=" + "é".repeat(64))),
  );
});

test("authentication allows typing time and repeat without exhausting failure budget, but expires without a decision", async (t) => {
  const h = await harness(t);
  const first = await h.start();
  assert.equal(first.waitSeconds, 20);
  for (let i = 0; i < 4; i++) {
    const reply = await h.say("");
    assert.equal(reply.end, false);
    assert.equal(reply.waitSeconds, 20);
  }
  assert.equal(h.state().failures, 0);
  assert.equal((await h.say("repeat")).text, first.text);
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
  );
  assert.match(p.render(first, h.session), /timeout="20"/);
  h.advanceTime(91000);
  assert.equal((await h.say("ready")).end, true);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});

test("spoken authentication code is twelve separate digit words with pauses and an explicit repeat", () => {
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
  );
  const xml = p.render(
    {
      text: "To authenticate, send slash voice then 0 1 2 3 4 5 in your enrolled Telegram chat. Then say ready.",
      turn: "t",
      waitSeconds: 20,
    },
    "s",
  );
  const digits = [
    ...xml.matchAll(
      /<Say[^>]*>(zero|one|two|three|four|five)<\/Say><Pause length="1"\/>/g,
    ),
  ].map((m) => m[1]);
  assert.deepEqual(digits, [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
  ]);
  assert.match(xml, />Again\.<\/Say>/);
  assert.match(xml, /timeout="20"/);
});

test("clear spoken choice phrases propose only the named option and successful steps reset consecutive clarifications", async (t) => {
  const h = await harness(t);
  await h.authenticate();
  await h.say("unknown review");
  assert.equal(h.state().failures, 1);
  const index = h
    .state()
    .inbox.findIndex((b) => b.caseId === "demo_candidate-choice");
  await h.say(`review ${index + 1}`);
  assert.equal(h.state().failures, 0);
  await h.say("I have checked");
  await h.say("I choose option A");
  assert.equal(h.state().phase, "confirm");
  assert.match(h.reply.text, /21707 kilograms/);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  await h.say("no");
  await h.say("select option A please");
  assert.equal(h.state().phase, "confirm");
  await h.say("I choose option A or B");
  assert.equal(h.state().phase, "choice");
  assert.equal(h.state().proposal, undefined);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
});

test("phonetic spoken options preserve exact read-back and require confirmation; ambiguous or unlisted choices do not submit", async (t) => {
  const h = await harness(t);
  await h.select();
  assert.match(h.reply.text, /Alpha/);
  await h.say("Alpha");
  assert.equal(h.state().phase, "confirm");
  assert.match(h.reply.text, /Option A, 21707 kilograms/);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  await h.say("Alpha or Bravo");
  assert.equal(h.state().proposal, undefined);
  await h.say("option eight");
  assert.equal(h.state().proposal, undefined);
  await h.say("I choose Alpha please");
  assert.equal(h.state().phase, "confirm");
  await h.say("yes");
  await h.advance();
  assert.equal(
    (await h.api.get("demo_candidate-choice")).resolution?.channel,
    "VOICE",
  );
});

test("natural review and evidence phrases retain inspection and explicit confirmation gates with longer response pauses", async (t) => {
  const h = await harness(t);
  await h.authenticate();
  const index = h
    .state()
    .inbox.findIndex((b) => b.caseId === "demo_candidate-choice");
  await h.say(`I choose review number ${index + 1} please`);
  assert.equal(h.state().phase, "evidence");
  assert.equal(h.reply.waitSeconds, 20);
  await h.say("I've checked");
  assert.equal(h.state().phase, "choice");
  await h.say("Alpha");
  assert.equal(h.reply.waitSeconds, 10);
  await h.say("yes, but no");
  assert.equal(h.state().proposal, undefined);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  await h.say("Alpha");
  await h.say("yes, please submit");
  assert.match(h.reply.text, /accepted by the simulator/);
});

test("supervised handset demo skips code, works past three minutes, and still requires evidence and explicit confirmation", async (t) => {
  const h = await harness(t, true);
  const start = await h.startOutbound();
  assert.doesNotMatch(start.text, /six|slash voice|authenticate/);
  assert.equal(h.state().authenticationMethod, "demo-handset");
  await assert.rejects(() =>
    h.voice.start("CAwrong", h.enrollment[0].phone, h.session),
  );
  await assert.rejects(() => h.voice.start("CAin", h.enrollment[0].phone));
  h.advanceTime(240000);
  await h.say("ready");
  const index = h
    .state()
    .inbox.findIndex((b) => b.caseId === "demo_candidate-choice");
  await h.say(`review ${index + 1}`);
  assert(h.documents.length > 0);
  await h.say("I've checked");
  await h.say("Alpha");
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  await h.say("yes");
  await h.advance();
  await h.say("status");
  assert.match(h.reply.text, /compared values now match/);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).resolution?.channel,
    "VOICE",
  );
});

test("handset demo expires at ten minutes and cannot reuse authorization after restart", async (t) => {
  const h = await harness(t, true);
  await h.startOutbound();
  h.advanceTime(600001);
  assert.equal((await h.say("ready")).end, true);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  h.restart();
  assert.equal(h.state().phase, "ended");
  await h.voice.tick();
  assert.equal(h.calls.length, 1);
});

test("ten-minute callback lifetime is opt-in for trial-demo and remains protected", () => {
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
    "trial-demo",
    600,
  );
  const xml = p.render({ text: "demo", turn: "b".repeat(32) }, "a".repeat(32));
  const url = / action="([^"]+)"/.exec(xml)![1].replaceAll("&amp;", "&");
  assert(
    Number(new URL(url).searchParams.get("expires")) - Date.now() > 590000,
  );
  assert(p.validateCapability(url));
  assert(!p.validateCapability(url.replace(/cap=[^&]+/, "cap=bad")));
  assert.throws(
    () =>
      new TwilioProvider(
        "ACtest",
        "secret",
        "+10000000000",
        "https://voice.example",
        "standard",
        600,
      ),
  );
  assert.throws(
    () =>
      new TwilioProvider(
        "ACtest",
        "secret",
        "+10000000000",
        "https://voice.example",
        "trial-demo",
        601,
      ),
  );
});

test("inbound trial HTTP call verifies provider metadata and uses the same confirmed simulator journey without dialing", async (t) => {
  const h = await harness(t, true);
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
    "trial-demo",
    600,
    "a".repeat(64),
  );
  const call = "CA" + "c".repeat(32),
    phone = h.enrollment[0].phone;
  const realFetch = globalThis.fetch;
  let checks = 0;
  t.mock.method(
    globalThis,
    "fetch",
    async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).startsWith("https://api.twilio.com/")) {
        checks++;
        assert.equal(init?.method, undefined);
        return new Response(
          JSON.stringify({
            sid: call,
            account_sid: "ACtest",
            direction: "inbound",
            from: phone,
            to: "+10000000000",
            status: "in-progress",
          }),
        );
      }
      return realFetch(input, init);
    },
  );
  h.provider.verifyInbound = p.verifyInbound.bind(p);
  const server = voiceApp(h.voice, p, p.origin).listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  t.after(() => server.close());
  const local = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const post = async (url: string, fields: Record<string, string>) => {
    const u = new URL(url);
    return realFetch(local + u.pathname + u.search, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(fields),
    });
  };
  const entry = p.inboundUrl();
  assert.equal(
    (
      await post(entry.slice(0, -1) + (entry.endsWith("a") ? "b" : "a"), {
        CallSid: call,
        From: phone,
      })
    ).status,
    403,
  );
  const denied = await post(entry, { CallSid: call, From: "+19999999999" });
  assert.match(await denied.text(), /unavailable/);
  assert.equal(checks, 0);
  const opened = await post(entry, { CallSid: call, From: phone });
  assert.equal(opened.status, 200);
  let xml = await opened.text();
  assert.match(xml, /Say ready/);
  const s = Object.values(h.voice.state.sessions)[0];
  assert.equal(s.direction, "inbound");
  assert.equal(s.authenticationMethod, "demo-handset");
  await post(entry, { CallSid: call, From: phone });
  assert.equal(Object.keys(h.voice.state.sessions).length, 1);
  assert.equal(checks, 1);
  const action = (x: string) =>
    / action="([^"]+)"/.exec(x)![1].replaceAll("&amp;", "&");
  const say = async (speech: string) => {
    const r = await post(action(xml), { CallSid: call, SpeechResult: speech });
    assert.equal(r.status, 200);
    xml = await r.text();
  };
  assert.equal(
    (await post(action(xml), { CallSid: "CAwrong", SpeechResult: "ready" }))
      .status,
    403,
  );
  await say("ready");
  const index = s.inbox.findIndex((b) => b.caseId === "demo_candidate-choice");
  await say(`review ${index + 1}`);
  assert(h.documents.length > 0);
  await say("I have checked");
  await say("Alpha");
  assert.equal(
    (await h.api.get("demo_candidate-choice")).review?.status,
    "OPEN",
  );
  await say("yes");
  await h.advance();
  await say("status");
  assert.match(xml, /compared values now match/);
  assert.match(xml, /<Hangup/);
  assert.equal(h.calls.length, 0);
  assert.equal(
    (await h.api.get("demo_candidate-choice")).history.filter(
      (x) => x.type === "DECISION_RECEIVED",
    ).length,
    1,
  );
});

test("inbound verification rejects completed, outbound, wrong-account, wrong-number and unavailable call records", async (t) => {
  const call = "CA" + "d".repeat(32),
    phone = "+60123456789";
  const p = new TwilioProvider(
    "ACtest",
    "secret",
    "+10000000000",
    "https://voice.example",
    "trial-demo",
    600,
    "a".repeat(64),
  );
  const valid = {
    sid: call,
    account_sid: "ACtest",
    direction: "inbound",
    from: phone,
    to: "+10000000000",
    status: "in-progress",
  };
  let body = valid,
    status = 200;
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(JSON.stringify(body), { status }),
  );
  for (const override of [
    { status: "completed" },
    { direction: "outbound-api" },
    { account_sid: "ACother" },
    { from: "+19999999999" },
    { to: "+19999999999" },
    { sid: "CAwrong" },
  ]) {
    body = { ...valid, ...override };
    assert.equal(await p.verifyInbound(call, phone), false);
  }
  body = valid;
  status = 404;
  assert.equal(await p.verifyInbound(call, phone), false);
  status = 200;
  assert.equal(await p.verifyInbound(call, phone), true);
  const entry = p.inboundUrl();
  assert.equal(new URL(entry).search, "");
  assert.equal(p.validateInboundCapability(entry + "?extra=1"), false);
  assert.equal(p.validateInboundCapability(entry + "#fragment"), false);
  assert.equal(p.validateInboundCapability(p.inboundUrl(Date.now() + 7200000)), false);
  assert.equal(p.validateInboundCapability(entry.slice(0, entry.lastIndexOf("/"))), false);
  assert.equal(
    p.validateInboundCapability(p.inboundUrl(Date.now() - 1)),
    false,
  );
  assert.equal(
    p.validateInboundCapability(p.inboundUrl() + "&expires=1"),
    false,
  );
  assert.equal(
    p.validateInboundCapability(
      p.inboundUrl().replace("/voice/inbound", "/voice/status"),
    ),
    false,
  );
});
