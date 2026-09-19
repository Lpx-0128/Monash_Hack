import express from "express";
import {
  existsSync,
  readFileSync,
  writeFileSync,
  renameSync,
  mkdirSync,
} from "node:fs";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { ApiError, DemoStore, statistics, summary } from "./store";
import { categories, statuses, workflows } from "../shared/validation";

/** Each browser receives a server-issued, DEMO-only guest session. No actor from JSON is trusted. */
export function createApp(
  options: {
    stateFile?: string;
    interaction?: { token: string; actors: string[] };
  } = {},
) {
  const app = express();
  const sessions = new Map<string, { store: DemoStore; touched: number }>();
  if (options.stateFile && existsSync(options.stateFile)) {
    const saved = JSON.parse(readFileSync(options.stateFile, "utf8"));
    for (const [token, data] of saved) {
      const store = new DemoStore();
      store.restore(data.store);
      sessions.set(token, { store, touched: data.touched });
    }
  }
  const persist = () => {
    if (!options.stateFile) return;
    mkdirSync(dirname(options.stateFile), { recursive: true });
    writeFileSync(
      options.stateFile + ".tmp",
      JSON.stringify(
        [...sessions].map(([token, s]) => [
          token,
          { touched: s.touched, store: s.store.snapshot() },
        ]),
      ),
    );
    renameSync(options.stateFile + ".tmp", options.stateFile);
  };
  app.disable("x-powered-by");
  app.use(express.json({ limit: "16kb" }));
  app.use((_req, res, next) => {
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "same-origin");
    next();
  });
  app.get(["/health", "/ready"], (_req, res) => res.json({ status: "ok" }));
  app.use("/api", (req, res, next) => {
    res.locals.channel = "DASHBOARD";
    if (req.headers.authorization) {
      const actor = req.header("X-Telegram-Actor");
      if (
        !options.interaction ||
        req.headers.authorization !== `Bearer ${options.interaction.token}`
      )
        return res
          .status(401)
          .json({
            error: {
              code: "UNAUTHORIZED",
              message: "Invalid service credential.",
            },
          });
      if (!actor || !options.interaction.actors.includes(actor))
        return res
          .status(403)
          .json({
            error: {
              code: "FORBIDDEN",
              message: "Actor is outside authorized scope.",
            },
          });
      res.locals.channel = "TELEGRAM";
      res.locals.actor = actor;
    }
    if (req.method !== "GET" && req.headers.origin) {
      const origin = new URL(req.headers.origin);
      if (origin.host !== req.headers.host)
        return res.status(403).json({
          error: {
            code: "FORBIDDEN",
            message: "Cross-origin writes are not allowed.",
          },
        });
    }
    const cookies = Object.fromEntries(
      (req.headers.cookie ?? "").split(";").map((v) => v.trim().split("=")),
    );
    let session = options.interaction
      ? sessions.get("shared-f2-demo")
      : cookies.harbor_demo
        ? sessions.get(cookies.harbor_demo)
        : undefined;
    if (!session) {
      const token = options.interaction ? "shared-f2-demo" : randomUUID();
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
    res.locals.actor ??= "demo-guest";
    res.setHeader("Cache-Control", "no-store");
    next();
  });
  const store = (res: express.Response) => res.locals.store as DemoStore;
  app.get("/api/demo/config", (_req, res) =>
    res.json({
      mode: "synthetic",
      contract: "2.1.1",
      milestone: options.interaction ? "F2" : "F1",
      actor_id: "demo-guest",
      decision_fault: store(res).decisionFault,
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
    persist();
    res.json({ ok: true });
  });
  app.post("/api/demo/advance", (_req, res) => {
    store(res).advance();
    persist();
    res.json({ ok: true });
  });
  app.post("/api/demo/fault", (req, res) => {
    store(res).fault = z
      .object({ mode: z.enum(["none", "outage", "slow", "denied"]) })
      .strict()
      .parse(req.body).mode;
    persist();
    res.json({ ok: true });
  });
  app.post("/api/demo/decision-fault", (req, res) => {
    store(res).decisionFault = z
      .strictObject({
        mode: z.enum(["none", "lost-response", "fail-resumption"]),
      })
      .parse(req.body).mode;
    persist();
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
    persist();
    res.status(result.status).json(result.body);
  });
  app.post("/api/v1/cases/:id/reprocess", (req, res) => {
    z.object({})
      .strict()
      .parse(req.body ?? {});
    const c = store(res).reprocess(req.params.id);
    persist();
    res.status(202).json(c);
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
    const before = store(res).snapshot();
    const c = store(res).decide(
      req.params.id,
      req.body,
      res.locals.actor,
      res.locals.channel,
    );
    try {
      persist();
    } catch (e) {
      store(res).restore(before);
      throw e;
    }
    if (store(res).decisionFault === "lost-response") {
      store(res).decisionFault = "none";
      persist();
      res.destroy();
      return;
    }
    res.status(202).json(c);
  });
  app.post("/api/v1/reviews/:id/notified", (req, res) => {
    if (res.locals.channel !== "TELEGRAM")
      throw new ApiError(403, "FORBIDDEN", "Interaction identity required.");
    const { run_id } = z.strictObject({ run_id: z.string() }).parse(req.body);
    const r = store(res).review(req.params.id),
      c = store(res).get(r.case_id);
    if (r.status !== "OPEN")
      throw new ApiError(409, "REVIEW_ALREADY_CLOSED", "Review closed.");
    if (r.run_id !== run_id || c.run.run_id !== run_id)
      throw new ApiError(409, "STALE_RUN", "Run replaced.");
    const before = store(res).snapshot();
    if (!r.notified_at) {
      r.notified_at = new Date().toISOString();
      c.history.push({
        event_id: randomUUID(),
        run_id,
        at: r.notified_at,
        type: "REVIEW_NOTIFIED",
        actor: { kind: "SYSTEM", id: null },
        summary: "Individual Telegram review delivered.",
        details: null,
      });
      try {
        persist();
      } catch (e) {
        store(res).restore(before);
        throw e;
      }
    }
    res.json(r);
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
      if (token !== "shared-f2-demo" && Date.now() - s.touched > 7200000)
        sessions.delete(token);
      else if (
        [...s.store.jobs.values()].some((job) => job.due <= Date.now())
      ) {
        const before = s.store.snapshot();
        try {
          s.store.tick();
          persist();
        } catch (e) {
          s.store.restore(before);
          console.error("Simulator worker failed", e);
        }
      }
    }
  }, 250);
  timer.unref();
  return { app, dispose: () => clearInterval(timer) };
}
