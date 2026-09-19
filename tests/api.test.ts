import test from "node:test";
import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { createApp } from "../server/app";
import {
  caseSchema,
  errorSchema,
  reviewListSchema,
  statsSchema,
  summarySchema,
} from "../shared/validation";

test("HTTP boundary: scope, filters, sessions, documents, replay, reset and F1 unavailability", async () => {
  const { app, dispose } = createApp();
  const server = app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  let cookie = "";
  async function get(path: string, method = "GET", body?: object) {
    const r = await fetch(base + path, {
      method,
      headers: {
        cookie,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    cookie = r.headers.get("set-cookie")?.split(";")[0] ?? cookie;
    return r;
  }
  try {
    assert.equal((await get("/health")).status, 200);
    assert.equal(
      (await (await get("/api/demo/config")).json()).contract,
      "2.1.1",
    );
    const list = await (await get("/api/v1/cases")).json();
    assert.equal(list.length, 18);
    list.forEach((c: unknown) => summarySchema.parse(c));
    const filtered = await (
      await get(
        "/api/v1/cases?has_open_review=true&workflow_status=AWAITING_HUMAN",
      )
    ).json();
    assert.equal(filtered.length, 5);
    assert.ok(
      filtered.every((c: { has_open_review: boolean }) => c.has_open_review),
    );
    statsSchema.parse(await (await get("/api/v1/stats")).json());
    reviewListSchema.parse(await (await get("/api/v1/reviews")).json());
    for (const path of [
      "/api/v1/cases?run_kind=EVAL",
      "/api/v1/stats?run_kind=EVAL",
      "/api/v1/reviews?run_kind=EVAL",
    ]) {
      const r = await get(path);
      assert.equal(r.status, 403);
      errorSchema.parse(await r.json());
    }
    for (const path of [
      "/api/v1/cases/eval_private",
      "/api/v1/documents/eval_private/content",
    ])
      assert.equal((await get(path)).status, 404);
    assert.equal(
      (await get("/api/v1/cases/eval_private/reprocess", "POST", {})).status,
      404,
    );
    const detail = caseSchema.parse(
      await (await get("/api/v1/cases/demo_match")).json(),
    );
    const d = await get(
      `/api/v1/documents/${detail.documents[0].document_id}/content`,
    );
    assert.match(d.headers.get("content-type")!, /text\/plain/);
    assert.match(await d.text(), /SYNTHETIC DEMONSTRATION/);
    const reviewCase = caseSchema.parse(
      await (await get("/api/v1/cases/demo_field-input")).json(),
    );
    const review = reviewCase.review!;
    assert.equal(
      (
        await get(`/api/v1/reviews/${review.review_id}/decision`, "POST", {
          run_id: review.run_id,
        })
      ).status,
      422,
    );
    assert.equal(
      (
        await get(`/api/v1/reviews/${review.review_id}/notified`, "POST", {
          run_id: review.run_id,
        })
      ).status,
      403,
    );
    assert.equal(
      caseSchema.parse(
        await (await get("/api/v1/cases/demo_field-input")).json(),
      ).review!.notified_at,
      null,
    );
    const replay = await get(
      "/api/v1/cases/demo_field-input/reprocess",
      "POST",
      {},
    );
    assert.equal(replay.status, 202);
    assert.equal(
      caseSchema.parse(await replay.json()).workflow_status,
      "PROCESSING",
    );
    assert.equal(
      (
        await get(`/api/v1/reviews/${review.review_id}/decision`, "POST", {
          run_id: review.run_id,
        })
      ).status,
      409,
    );
    const other = await fetch(base + "/api/v1/cases/demo_field-input");
    assert.equal(
      caseSchema.parse(await other.json()).run.run_id,
      review.run_id,
      "Other session is isolated",
    );
    await get("/api/demo/advance", "POST", {});
    assert.equal(
      caseSchema.parse(
        await (await get("/api/v1/cases/demo_field-input")).json(),
      ).workflow_status,
      "AWAITING_HUMAN",
    );
    await get("/api/demo/reset", "POST", { empty: true });
    assert.equal(
      statsSchema.parse(await (await get("/api/v1/stats")).json()).total_cases,
      0,
    );
    const created = await get("/api/v1/cases", "POST", {
      email_id: "demo_match",
    });
    assert.equal(created.status, 202);
    assert.equal(caseSchema.parse(await created.json()).email.category, null);
    assert.equal(
      (await get("/api/v1/cases", "POST", { email_id: "demo_match" })).status,
      200,
    );
    assert.equal(
      (await get("/api/v1/cases?workflow_status=INVENTED")).status,
      422,
    );
  } finally {
    server.close();
    dispose();
  }
});
