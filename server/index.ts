import { createApp } from "./app";
import express from "express";
import path from "node:path";
import { loadDataset } from "./dataset";
import { hostedAuth } from "./hosted-auth";
import { accessSync, constants } from "node:fs";
const hosted = process.env.HARBOR_HOSTED === "true";
const mode =
  process.env.BACKEND_MODE ??
  (process.env.VITE_API_MODE === "live" ? "real" : "mock");
if (!["mock", "real"].includes(mode))
  throw new Error("BACKEND_MODE must be mock or real");
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const origin = process.env.F2_DASHBOARD_URL ?? "";
const telegramUser = process.env.TELEGRAM_BOT_USERNAME ?? "";
if (
  hosted &&
  (!/^https:\/\//.test(origin) ||
    !/^[A-Za-z0-9_]{5,32}$/.test(telegramUser) ||
    !process.env.F2_BACKEND_TOKEN)
)
  throw new Error(
    "Hosted mode requires HTTPS dashboard URL, bot username and service credential",
  );
if (
  hosted &&
  (process.env.F3_PROVIDER !== "azure-foundry" ||
    process.env.F3_ENABLED !== "true" ||
    process.env.VOICE_ENABLED === "true")
)
  throw new Error("Hosted release requires Azure interpretation and voice disabled");

const app = express();
if (hosted)
  app.use(
    hostedAuth(
      process.env.HARBOR_AUTH_FILE ?? ".local/hosted-auth.json",
      process.env.HARBOR_LINK_SECRET ?? "",
      new URL(origin).origin,
    ),
  );

if (mode === "real") {
  app.use(express.json({ limit: "16kb" }));
  const proxyToBackend = async (req: express.Request, res: express.Response) => {
    try {
      const target = new URL(req.originalUrl, backendUrl);
      const headers = new Headers();
      for (const [key, val] of Object.entries(req.headers)) {
        if (val && key.toLowerCase() !== "host") {
          if (Array.isArray(val)) {
            val.forEach((v) => headers.append(key, v));
          } else {
            headers.set(key, val);
          }
        }
      }
      const init: RequestInit = {
        method: req.method,
        headers,
      };
      if (req.method !== "GET" && req.method !== "HEAD") {
        init.body = JSON.stringify(req.body);
      }
      const response = await fetch(target.toString(), init);
      res.status(response.status);
      response.headers.forEach((val, key) => {
        if (
          !["content-encoding", "transfer-encoding"].includes(
            key.toLowerCase(),
          )
        ) {
          res.setHeader(key, val);
        }
      });
      const data = Buffer.from(await response.arrayBuffer());
      res.send(data);
    } catch (err: any) {
      res.status(502).json({
        error: {
          code: "BACKEND_UNAVAILABLE",
          message: `Could not reach backend at ${backendUrl}: ${err.message}`,
        },
      });
    }
  };

  app.get(["/health", "/ready"], proxyToBackend);
  app.use("/api/v1", proxyToBackend);
  app.get("/api/demo/config", (_req, res) =>
    res.json({
      mode: "real",
      contract: "2.1.2",
      milestone: "F1",
      actor_id: "demo-guest",
    }),
  );
} else {
  const { app: simulator } = createApp({
    dataset: process.env.MOCK_DATASET_FILE
      ? loadDataset(process.env.MOCK_DATASET_FILE)
      : undefined,
    hosted: hosted ? { telegramUrl: `https://t.me/${telegramUser}` } : undefined,
    stateFile: process.env.SIMULATOR_STATE_FILE ?? ".local/simulator-state.json",
    voice: process.env.VOICE_BACKEND_TOKEN
      ? {
          token: process.env.VOICE_BACKEND_TOKEN,
          actors: (process.env.F2_ACTORS ?? "").split(",").filter(Boolean),
        }
      : undefined,
    interaction: process.env.F2_BACKEND_TOKEN
      ? {
          token: process.env.F2_BACKEND_TOKEN,
          actors: (process.env.F2_ACTORS ?? "").split(",").filter(Boolean),
        }
      : undefined,
  });

  if (hosted)
    app.get("/ready", async (_req, res) => {
      let storage = false,
        gateway = false;
      try {
        accessSync(
          path.dirname(
            process.env.SIMULATOR_STATE_FILE ?? ".local/simulator-state.json",
          ),
          constants.W_OK,
        );
        storage = true;
      } catch {
        /* Readiness fails closed. */
      }
      try {
        gateway = (
          await fetch("http://127.0.0.1:5175/health", {
            signal: AbortSignal.timeout(2000),
          })
        ).ok;
      } catch {
        /* Process remains live while transport recovers. */
      }
      const aiConfigured =
        !!process.env.AZURE_FOUNDRY_BASE_URL &&
        !!process.env.AZURE_FOUNDRY_API_KEY;
      res.status(storage && gateway && aiConfigured ? 200 : 503).json({
        status: storage && gateway && aiConfigured ? "ready" : "degraded",
        storage,
        gateway,
        ai_configured: aiConfigured,
      });
    });

  app.use(simulator);
}
if (process.argv.includes("--dev")) {
  const { createServer } = await import("vite");
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "spa",
  });
  app.use(vite.middlewares);
} else {
  app.use(express.static(path.resolve("dist")));
  app.get("/{*path}", (_req, res) =>
    res.sendFile(path.resolve("dist/index.html")),
  );
}
const port = Number(process.env.PORT ?? 5173);
app.listen(port, process.env.HOST ?? "127.0.0.1", () =>
  console.log(
    `Harbor Review: http://localhost:${port} (${mode === "real" ? "live API proxy -> " + backendUrl : "synthetic F1 simulator"})`,
  ),
);
