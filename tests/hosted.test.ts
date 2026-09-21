import test from "node:test";
import assert from "node:assert/strict";
import express from "express";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { hostedAuth } from "../server/hosted-auth";
import { dashboardLink } from "../shared/dashboard-link";
import { createApp } from "../server/app";
import { DemoStore, statistics } from "../server/store";
import { auditDocuments } from "../server/fixtures";

test("Full dataset mock preserves every source identity and marks simulated provenance", () => {
  const emails = Array.from({ length: 520 }, (_, i) => ({ email_id: `email_${String(i+1).padStart(3,"0")}`, from: "sender@example.test", subject: `Email ${i+1}`, body: "Original source body", attachments: i % 3 ? [] : ["attachments/SI.txt", "attachments/BL.txt"] }));
  const store = new DemoStore(emails);
  assert.equal(statistics([...store.cases.values()]).total_cases, 520);
  assert.equal(new Set([...store.cases.values()].map(c => c.run.run_id)).size, 520);
  for (const e of emails) {
    const c = store.get(e.email_id);
    assert.equal(c.email.received_at, null);
    assert.deepEqual(c.history[0].details?.source_email, e);
    assert.equal(c.history[0].details?.outcome_provenance, "SIMULATED_NOT_GROUND_TRUTH");
    assert.equal(c.review?.case_id ?? e.email_id, e.email_id);
    auditDocuments(c, store.documents);
  }
  const restored = new DemoStore(emails);
  restored.restore(store.snapshot());
  assert.equal(restored.cases.size, 520);
});

test("Hosted sample is read-only; Telegram links isolate actors, resist replay/tampering and survive restart", async () => {
  const dir = mkdtempSync(join(tmpdir(), "harbor-hosted-"));
  const secret = "s".repeat(64), backend = "b".repeat(64), origin = "https://harbor.example";
  const stateFile = join(dir, "state.json"), authFile = join(dir, "auth.json");
  async function start() {
    const app = express();
    app.use(hostedAuth(authFile, secret, origin, false));
    const instance = createApp({ stateFile, hosted: { telegramUrl: "https://t.me/example_bot" }, interaction: { token: backend, actors: [] } });
    app.use(instance.app);
    const server = app.listen(0, "127.0.0.1");
    await once(server, "listening");
    return { base: `http://127.0.0.1:${(server.address() as import("node:net").AddressInfo).port}`, close: async () => { instance.dispose(); server.close(); await once(server,"close"); } };
  }
  let live = await start();
  let cookie = "", token = "", caseId = "";
  const send = (path: string, init: RequestInit = {}) => fetch(live.base + path, init);
  const exchange = (value: string, requestOrigin = origin) => send("/api/session/exchange", { method: "POST", headers: { "Content-Type": "application/json", Origin: requestOrigin }, body: JSON.stringify({ token: value }) });
  try {
    assert.equal((await send("/api/v1/cases/demo_match/reprocess", { method:"POST", headers:{Origin:origin} })).status,403);
    token = new URL(dashboardLink(origin,"1001","/",secret)).hash.slice(1);
    assert.equal((await exchange(token,"https://evil.example")).status,403);
    assert.equal((await exchange(token + "x")).status,401);
    const connected = await exchange(token);
    assert.equal(connected.status,200);
    assert.match(connected.headers.get("set-cookie")!, /HttpOnly/);
    cookie = connected.headers.get("set-cookie")!.split(";")[0];
    assert.equal((await exchange(token)).status,401);
    const mine = await (await send("/api/v1/cases",{headers:{Cookie:cookie}})).json();
    caseId = mine[0].case_id;
    const viaBot = await (await send("/api/v1/cases",{headers:{Authorization:`Bearer ${backend}`,"X-Telegram-Actor":"1001"}})).json();
    assert.equal(mine[0].run_id,viaBot[0].run_id);
    const other = await (await send("/api/v1/cases",{headers:{Authorization:`Bearer ${backend}`,"X-Telegram-Actor":"1002"}})).json();
    assert.notEqual(mine[0].run_id,other[0].run_id);
    const detail = await (await send(`/api/v1/cases/${caseId}`,{headers:{Cookie:cookie}})).json();
    const doc = detail.documents[0]?.document_id;
    if (doc) assert.equal((await send(`/api/v1/documents/${doc}/content`, { headers:{Authorization:`Bearer ${backend}`,"X-Telegram-Actor":"1002"} })).status,404);
    assert.equal((await send("/api/demo/reset", { method:"POST",headers:{Cookie:cookie,Origin:origin} })).status,404);
  } finally { await live.close(); }
  live = await start();
  try {
    assert.equal((await exchange(token)).status,401);
    assert.equal((await send(`/api/v1/cases/${caseId}`,{headers:{Cookie:cookie}})).status,200);
  } finally { await live.close(); }
});
