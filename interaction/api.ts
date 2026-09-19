import {
  assertDemo,
  caseSchema,
  summarySchema,
  reviewSchema,
  errorSchema,
} from "../shared/validation";
import type { Case, DecisionRequest } from "../shared/types";
export class RemoteError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
export class ReviewApi {
  constructor(
    public base: string,
    private token: string,
    public actor: string,
  ) {}
  async request(path: string, body?: unknown) {
    const r = await fetch(this.base + "/api/v1" + path, {
      method: body === undefined ? "GET" : "POST",
      redirect: "error",
      signal: AbortSignal.timeout(10000),
      headers: {
        Authorization: `Bearer ${this.token}`,
        "X-Telegram-Actor": this.actor,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      const e = errorSchema.parse(await r.json());
      throw new RemoteError(r.status, e.error.code);
    }
    return r;
  }
  async list() {
    return summarySchema
      .array()
      .parse(await (await this.request("/cases?run_kind=DEMO")).json());
  }
  async get(id: string): Promise<Case> {
    const c = caseSchema.parse(
      await (await this.request("/cases/" + encodeURIComponent(id))).json(),
    );
    assertDemo(c);
    return c;
  }
  async decide(d: DecisionRequest) {
    const r = await this.request(
      "/reviews/" + encodeURIComponent(d.review_id) + "/decision",
      d,
    );
    if (r.status !== 202) throw new Error("Uncertain acceptance");
    const c = caseSchema.parse(await r.json());
    assertDemo(c);
    return c;
  }
  async notified(review: string, run: string) {
    return reviewSchema.parse(
      await (
        await this.request(
          "/reviews/" + encodeURIComponent(review) + "/notified",
          { run_id: run },
        )
      ).json(),
    );
  }
  async document(c: Case, id: string) {
    assertDemo(c);
    const d = c.documents.find((d) => d.document_id === id && d.demo_safe);
    if (!d) throw new Error("Document outside case scope");
    const r = await this.request(
      "/documents/" + encodeURIComponent(id) + "/content",
    );
    const bytes = Buffer.from(await r.arrayBuffer());
    if (bytes.length > 8_000_000)
      throw new Error("Document too large for demonstration");
    return { filename: d.filename, data: bytes.toString("base64") };
  }
}
