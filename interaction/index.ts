import express from "express";
import { z } from "zod";
import {
  mkdirSync,
  openSync,
  closeSync,
  unlinkSync,
  readFileSync,
  writeFileSync,
  renameSync,
  existsSync,
} from "node:fs";
import { dirname } from "node:path";
import { ReviewApi } from "./api";
import { ReviewEngine, type Recipient, type Button } from "./engine";
import { VoiceService } from "./voice";
import { TwilioProvider } from "./voice-provider";
import { voiceApp } from "./voice-http";
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
const enrollmentFile = state + ".recipients.json";
if (process.env.HARBOR_HOSTED === "true" && existsSync(enrollmentFile)) {
  const saved = z.array(z.strictObject({ actor: z.string().regex(/^\d{1,20}$/), chat: z.string().regex(/^\d{1,20}$/) })).max(99).parse(JSON.parse(readFileSync(enrollmentFile, "utf8")));
  for (const r of saved) if (!recipients.some(x => x.actor === r.actor && x.chat === r.chat)) recipients.push(r);
}
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
    edit: async (chat, message, buttons, text) => {
      await outbound({ chat, message, buttons, ...(text ? { text } : {}) });
    },
  },
  required("F2_DASHBOARD_URL"),
  Date.now,
  process.env.F3_ENABLED === "true"
    ? async (input) => {
        const response = await fetch(bridge + "/interpret", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${secret}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(input),
          signal: AbortSignal.timeout(25000),
        });
        if (!response.ok) throw new Error("Copilot interpretation unavailable");
        return response.json();
      }
    : undefined,
);
let voice: VoiceService | undefined;
if (process.env.VOICE_ENABLED === "true") {
  // V1 is deliberately pinned to the local simulator, not an arbitrary backend URL.
  const base = required("F2_BACKEND_URL");
  if (new URL(base).hostname !== "127.0.0.1")
    throw new Error("V1 voice requires the local simulator");
  const check = await fetch(base + "/api/demo/config");
  const config = await check.json();
  if (config.mode !== "synthetic" || config.contract !== "2.1.2")
    throw new Error("V1 requires the v2.1.2 simulator");
  const voiceToken = required("VOICE_BACKEND_TOKEN");
  if (voiceToken.length < 32 || voiceToken === backend)
    throw new Error("Use a distinct voice service credential");
  const enrollment = z
    .array(
      z.strictObject({
        actor: z.string(),
        phone: z.string().regex(/^\+[1-9]\d{7,14}$/),
        optedIn: z.boolean(),
        outboundCaseId: z.string().optional(),
      }),
    )
    .length(1)
    .parse(JSON.parse(required("VOICE_ENROLLMENT")));
  if (!recipients.some((r) => r.actor === enrollment[0].actor))
    throw new Error("Voice actor must be an enrolled Telegram actor");
  const providerMode = z
    .enum(["standard", "trial", "trial-demo"])
    .parse(process.env.VOICE_PROVIDER_MODE ?? "standard");
  const skipDemoChallenge = process.env.VOICE_DEMO_SKIP_CHALLENGE === "true";
  if (skipDemoChallenge && providerMode !== "trial-demo")
    throw new Error("Demo handset access requires trial-demo mode");
  const cap = z.coerce
    .number()
    .int()
    .min(30)
    .max(providerMode === "trial-demo" ? 600 : 180)
    .parse(process.env.VOICE_CALL_SECONDS ?? 90);
  const hour = z.coerce.number().int().min(0).max(23);
  if (
    providerMode === "trial-demo" &&
    process.env.VOICE_TRIAL_DEMO_ACKNOWLEDGED !== "true"
  )
    throw new Error(
      "Trial demo requires acknowledgment of capability authentication and application-only deadline",
    );
  const provider = new TwilioProvider(
    required("TWILIO_ACCOUNT_SID"),
    required("TWILIO_AUTH_TOKEN"),
    required("TWILIO_FROM"),
    required("VOICE_PUBLIC_URL"),
    providerMode,
    providerMode === "trial-demo" ? cap : 180,
    process.env.VOICE_INBOUND_ENABLED === "true"
      ? required("VOICE_INBOUND_KEY")
      : undefined,
  );
  voice = new VoiceService(
    process.env.VOICE_STATE_FILE ?? ".local/voice-state.json",
    engine,
    (a) => new ReviewApi(base, voiceToken, a, "VOICE"),
    provider,
    enrollment,
    Date.now,
    cap,
    {
      start: hour.parse(process.env.VOICE_QUIET_START ?? 22),
      end: hour.parse(process.env.VOICE_QUIET_END ?? 8),
    },
    skipDemoChallenge,
  );
  voiceApp(voice, provider, provider.origin, (event) => {
    // Fixed metadata only: never log caller numbers, URLs, credentials or speech.
    console.info("Voice inbound diagnostic", JSON.stringify(event));
  }).listen(
    Number(process.env.VOICE_PORT ?? 5177),
    "127.0.0.1",
  );
}
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
    const u = parsed.data;
    if (process.env.HARBOR_HOSTED === "true" && u.text === "/start" && /^\d{1,20}$/.test(u.actor) && u.actor === u.chat && !recipients.some(r => r.actor === u.actor && r.chat === u.chat)) {
      if (recipients.length >= 99) return void res.status(429).json({ error: "Enrollment capacity reached" });
      const candidate = [...recipients, { actor: u.actor, chat: u.chat }];
      writeFileSync(enrollmentFile + ".tmp", JSON.stringify(candidate.map(({ actor, chat }) => ({ actor, chat }))), { mode: 0o600 });
      renameSync(enrollmentFile + ".tmp", enrollmentFile);
      recipients.push({ actor: u.actor, chat: u.chat });
    }
    if (!(await voice?.approve(parsed.data))) await engine.inbound(parsed.data);
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
    try {
      await voice?.tick();
    } catch {
      console.error("Voice unavailable; Telegram remains active.");
    }
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
