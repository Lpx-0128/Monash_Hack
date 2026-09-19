import express from "express";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { ApiError, DemoStore, statistics, summary } from "./store";
import { categories, statuses, workflows } from "../shared/validation";

/** Each browser receives a server-issued, DEMO-only guest session. No actor from JSON is trusted. */
export function createApp() {
  const app = express();
  const sessions = new Map<string, { store: DemoStore; touched: number }>();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "16kb" }));
  app.use((_req, res, next) => {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "same-origin");
    next();
  });
  app.get(["/health", "/ready"], (_req, res) => res.json({ status: "ok" }));
  app.use("/api", (req, res, next) => {
    if (req.method !== "GET" && req.headers.origin) {
      const origin = new URL(req.headers.origin);
      if (origin.host !== req.headers.host)
        return res
          .status(403)
          .json({
            error: {
              code: "FORBIDDEN",
              message: "Cross-origin writes are not allowed.",
            },
          });
    }
    const cookies = Object.fromEntries(
      (req.headers.cookie ?? "").split(";").map((v) => v.trim().split("=")),
    );
    let session = cookies.harbor_demo
      ? sessions.get(cookies.harbor_demo)
      : undefined;
    if (!session) {
      const token = randomUUID();
      session = { store: new DemoStore(), touched: Date.now() };
      sessions.set(token, session);
      res.cookie("harbor_demo", token, {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.COOKIE_SECURE === "true",
        maxAge: 7200000,
        path: "/",
      });
    }
    session.touched = Date.now();
    res.locals.store = session.store;
    res.setHeader("Cache-Control", "no-store");
    next();
  });
  const store = (res: express.Response) => res.locals.store as DemoStore;
  app.get("/api/demo/config", (_req, res) =>
    res.json({
      mode: "synthetic",
      contract: "2.1.1",
      milestone: "F0",
      fault: store(res).fault,
    }),
  );
  app.post("/api/demo/reset", (req, res) => {
    store(res).reset(
      z
        .object({ empty: z.boolean().optional() })
        .strict()
        .parse(req.body ?? {}).empty,
    );
    res.json({ ok: true });
  });
  app.post("/api/demo/advance", (_req, res) => {
    store(res).advance();
    res.json({ ok: true });
  });
  app.post("/api/demo/fault", (req, res) => {
    store(res).fault = z
      .object({ mode: z.enum(["none", "outage", "slow", "denied"]) })
      .strict()
      .parse(req.body).mode;
    res.json({ ok: true });
  });
  app.use("/api/v1", async (req, res, next) => {
    if (req.query.run_kind !== undefined && req.query.run_kind !== "DEMO")
      return next(
        new ApiError(
          403,
          "FORBIDDEN",
          "This guest session can access approved DEMO fixtures only.",
        ),
      );
    const mode = store(res).fault;
    if (mode === "outage")
      return next(
        new ApiError(
          503,
          "INTERNAL",
          "Simulated service outage. Restore the connection in Demo controls.",
        ),
      );
    if (mode === "denied")
      return next(
        new ApiError(
          403,
          "FORBIDDEN",
          "Simulated access denied. Restore access in Demo controls.",
        ),
      );
    if (mode === "slow") await new Promise((r) => setTimeout(r, 2500));
    next();
  });
  app.get("/api/v1/cases", (req, res) => {
    const q = z
      .object({
        workflow_status: z.enum(workflows).optional(),
        category: z.enum(categories).optional(),
        final_status: z.enum(statuses).optional(),
        has_open_review: z.enum(["true", "false"]).optional(),
        run_kind: z.literal("DEMO").optional(),
      })
      .strict()
      .parse(req.query);
    res.json(store(res).list(q));
  });
  app.get("/api/v1/cases/:id", (req, res) =>
    res.json(store(res).get(req.params.id)),
  );
  app.post("/api/v1/cases", (req, res) => {
    const body = z.object({ email_id: z.string() }).strict().parse(req.body);
    const result = store(res).create(body.email_id);
    res.status(result.status).json(result.body);
  });
  app.post("/api/v1/cases/:id/reprocess", (req, res) => {
    z.object({})
      .strict()
      .parse(req.body ?? {});
    res.status(202).json(store(res).reprocess(req.params.id));
  });
  app.get("/api/v1/stats", (_req, res) =>
    res.json(statistics([...store(res).cases.values()])),
  );
  app.get("/api/v1/reviews", (req, res) => {
    const q = z
      .object({
        status: z.enum(["OPEN", "CLOSED"]).optional(),
        notified: z.enum(["true", "false"]).optional(),
        run_kind: z.literal("DEMO").optional(),
      })
      .strict()
      .parse(req.query);
    res.json(
      [...store(res).cases.values()]
        .filter(
          (c) =>
            c.review &&
            (!q.status || c.review.status === q.status) &&
            (q.notified === undefined ||
              String(!!c.review.notified_at) === q.notified),
        )
        .map((c) => ({ review: c.review, case: summary(c) })),
    );
  });
  app.get("/api/v1/documents/:id/content", (req, res) => {
    const d = store(res).document(req.params.id);
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    res.setHeader(
      "Content-Disposition",
      `inline; filename="${d.meta.filename}"`,
    );
    res.send(d.text);
  });
  app.post("/api/v1/reviews/:id/decision", (req, res) => {
    const r = store(res).review(req.params.id);
    if (r.status === "CLOSED")
      throw new ApiError(
        409,
        "REVIEW_ALREADY_CLOSED",
        "This review has been handled or superseded.",
      );
    if (req.body?.run_id !== r.run_id)
      throw new ApiError(
        409,
        "STALE_RUN",
        "The request belongs to a different run.",
      );
    throw new ApiError(
      422,
      "ACTION_NOT_ALLOWED",
      "Decision submission is unavailable in F0. This read-only review preview is reserved for F1.",
    );
  });
  app.post("/api/v1/reviews/:id/notified", () => {
    throw new ApiError(
      403,
      "FORBIDDEN",
      "Notification updates require an interaction-service identity; unavailable in F0.",
    );
  });
  app.use("/api", () => {
    throw new ApiError(404, "NOT_FOUND", "Endpoint unavailable.");
  });
  app.use(
    (
      error: unknown,
      _req: express.Request,
      res: express.Response,
      _next: express.NextFunction,
    ) => {
      const e =
        error instanceof ApiError
          ? error
          : error instanceof z.ZodError
            ? new ApiError(
                422,
                "INVALID_VALUE",
                "Invalid request shape or filter.",
              )
            : new ApiError(500, "INTERNAL", "Unexpected server error.");
      if (!(error instanceof ApiError) && !(error instanceof z.ZodError))
        console.error(error);
      res
        .status(e.status)
        .json({ error: { code: e.code, message: e.message } });
    },
  );
  const timer = setInterval(() => {
    for (const [token, s] of sessions) {
      if (Date.now() - s.touched > 7200000) sessions.delete(token);
      else s.store.tick();
    }
  }, 250);
  timer.unref();
  return { app, dispose: () => clearInterval(timer) };
}
