import { createApp } from "./app";
import express from "express";
import path from "node:path";
const { app } = createApp({
  stateFile: process.env.SIMULATOR_STATE_FILE ?? ".local/simulator-state.json",
  interaction: process.env.F2_BACKEND_TOKEN
    ? {
        token: process.env.F2_BACKEND_TOKEN,
        actors: (process.env.F2_ACTORS ?? "").split(",").filter(Boolean),
      }
    : undefined,
});
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
    `Harbor Review: http://localhost:${port} (synthetic F1 simulator)`,
  ),
);
