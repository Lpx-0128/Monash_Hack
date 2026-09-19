import express from "express";
import { z } from "zod";
import {
  mkdirSync,
  openSync,
  closeSync,
  unlinkSync,
  readFileSync,
  writeFileSync,
  existsSync,
} from "node:fs";
import { dirname } from "node:path";
import { ReviewApi } from "./api";
import { ReviewEngine, type Recipient, type Button } from "./engine";
const required = (name: string) => {
  const v = process.env[name];
  if (!v) throw new Error(`Configure ${name} in the private environment file`);
  return v;
};
const secret = required("F2_BRIDGE_TOKEN"),
  backend = required("F2_BACKEND_TOKEN");
if (secret.length < 32 || backend.length < 32)
  throw new Error("Service credentials must have at least 32 characters");
const recipients = z
  .array(
    z
      .object({
        actor: z.string(),
        chat: z.string(),
        operator: z.boolean().optional(),
      })
      .strict(),
  )
  .parse(JSON.parse(required("F2_RECIPIENTS"))) as Recipient[];
const state = process.env.F2_STATE_FILE ?? ".local/f2-state.json";
mkdirSync(dirname(state), { recursive: true });
// Fail closed for a live/reused PID; recover only a positively dead owner.
if (existsSync(state + ".lock")) {
  const pid = Number(readFileSync(state + ".lock", "utf8"));
  if (!Number.isSafeInteger(pid) || pid <= 0)
    throw new Error("Invalid notifier lock; inspect owner before removing it");
  try {
    process.kill(pid, 0);
    throw new Error("A notifier already owns this state file");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ESRCH")
      unlinkSync(state + ".lock");
    else throw e;
  }
}
const lock = openSync(state + ".lock", "wx", 0o600);
writeFileSync(lock, String(process.pid));
process.on("exit", () => {
  closeSync(lock);
  unlinkSync(state + ".lock");
});
process.on("SIGINT", () => process.exit(0));
process.on("SIGTERM", () => process.exit(0));
const bridge = process.env.F2_BRIDGE_URL ?? "http://127.0.0.1:5175";
if (new URL(bridge).hostname !== "127.0.0.1")
  throw new Error("Hermes bridge must be loopback");
async function outbound(body: unknown) {
  const r = await fetch(bridge + "/send", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${secret}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  if (!r.ok) throw new Error("Hermes transport unavailable");
  return z.object({ message: z.string() }).parse(await r.json()).message;
}
const engine = new ReviewEngine(
  state,
  recipients,
  (a) => new ReviewApi(required("F2_BACKEND_URL"), backend, a),
  {
    send: (chat: string, text: string, buttons?: Button[][]) =>
      outbound({ chat, text, buttons }),
    document: (chat, file) => outbound({ chat, ...file }),
  },
  required("F2_DASHBOARD_URL"),
);
const app = express();
app.use(express.json({ limit: "32kb" }));
app.post("/update", async (req, res) => {
  if (req.header("Authorization") !== `Bearer ${secret}`) {
    res.sendStatus(401);
    return;
  }
  const parsed = z
    .strictObject({
      id: z.string(),
      actor: z.string(),
      chat: z.string(),
      message: z.string(),
      reply: z.string().optional(),
      text: z.string().max(8192).optional(),
      callback: z.string().max(64).optional(),
    })
    .safeParse(req.body);
  if (!parsed.success) {
    res.sendStatus(400);
    return;
  }
  try {
    await engine.inbound(parsed.data);
    res.json({ ok: true });
  } catch {
    res.status(503).json({ error: "Interaction service unavailable" });
  }
});
app.listen(Number(process.env.F2_PORT ?? 5174), "127.0.0.1");
let failures = 0;
async function poll() {
  try {
    await engine.tick();
    failures = 0;
  } catch {
    failures++;
    console.error(
      "F2 backend/transport unavailable; backing off (no credentials logged).",
    );
  }
  setTimeout(poll, Math.min(60000, 4000 * 2 ** Math.min(failures, 4)));
}
void poll();
