import express from "express";
import { VoiceService } from "./voice";
import type { VoiceProvider } from "./voice-provider";

export type InboundDiagnostic = {
  method: string;
  hasCall: boolean;
  hasFrom: boolean;
  hasSignature: boolean;
  capabilityValid: boolean;
  pathCapabilityPresent: boolean;
  queryPresent: boolean;
  expiryState: "missing" | "expired" | "future" | "current";
  status: number;
  elapsedMs: number;
};

/** Expose only these routes through the HTTPS tunnel, never /update or the bridge. */
export function voiceApp(
  service: VoiceService,
  provider: VoiceProvider,
  origin: string,
  diagnoseInbound?: (event: InboundDiagnostic) => void,
) {
  const app = express();
  app.disable("x-powered-by");
  app.use(express.urlencoded({ extended: false, limit: "16kb" }));
  app.use(async (req, res, next) => {
    const url = origin.replace(/\/$/, "") + req.originalUrl;
    if (req.path.startsWith("/voice/inbound") && diagnoseInbound) {
      const started = Date.now();
      const parsed = new URL(url);
      const expiry = Number(/^\/voice\/inbound\/(\d{13})\//.exec(parsed.pathname)?.[1]);
      const summary = {
        method: req.method,
        hasCall: typeof req.body?.CallSid === "string",
        hasFrom: typeof req.body?.From === "string",
        hasSignature: !!req.header("X-Twilio-Signature"),
        capabilityValid: provider.validateInboundCapability?.(url) ?? false,
        pathCapabilityPresent: /^\/voice\/inbound\/\d{13}\/[a-f0-9]{64}$/.test(parsed.pathname),
        queryPresent: !!parsed.search,
        expiryState: (!Number.isFinite(expiry) ? "missing" : expiry <= started ? "expired" : expiry > started + 3600000 ? "future" : "current") as InboundDiagnostic["expiryState"],
      };
      res.once("finish", () => {
        diagnoseInbound({ ...summary, status: res.statusCode, elapsedMs: Date.now() - started });
      });
    }
    if (
      req.method !== "POST" ||
      !req.body ||
      Object.values(req.body).some((v) => typeof v !== "string")
    ) {
      res.sendStatus(403);
      return;
    }
    const signature = req.header("X-Twilio-Signature") ?? "";
    if (!provider.validate(url, req.body, signature)) {
      if (!signature && provider.validateInboundCapability?.(url)) {
        res.setHeader("Cache-Control", "no-store");
        next();
        return;
      }
      // Explicit synthetic trial mode only. A capability is a bearer credential,
      // not proof of Twilio identity or a signature over the request body.
      // Never accept an invalid supplied signature through this alternative.
      if (
        signature ||
        !provider.validateCapability?.(url) ||
        typeof req.query.session !== "string"
      ) {
        res.sendStatus(403);
        return;
      }
      const call = await service.transportCall(req.query.session);
      if (!call || (req.body.CallSid && req.body.CallSid !== call)) {
        res.sendStatus(403);
        return;
      }
      req.body.CallSid = call;
      req.body.From ??= "";
    }
    res.setHeader("Cache-Control", "no-store");
    next();
  });
  app.post(["/voice/start", "/voice/inbound", "/voice/inbound/:expires/:cap"], async (req, res) => {
    try {
      if (
        typeof req.body.CallSid !== "string" ||
        typeof req.body.From !== "string"
      )
        throw new Error("Invalid callback");
      const session =
        typeof req.query.session === "string" ? req.query.session : undefined;
      const r = await service.start(req.body.CallSid, req.body.From, session);
      res
        .type("text/xml")
        .send(
          provider.render(
            r,
            "session" in r ? (r.session as string) : (session ?? ""),
          ),
        );
    } catch {
      res.type("text/xml").send(
        provider.render(
          {
            text: "This call is unavailable. Please use Telegram.",
            end: true,
            turn: "",
          },
          "",
        ),
      );
    }
  });
  app.post("/voice/turn", async (req, res) => {
    try {
      if (
        typeof req.body.CallSid !== "string" ||
        typeof req.query.session !== "string" ||
        typeof req.query.turn !== "string"
      )
        throw new Error("Invalid callback");
      const r = await service.turn(
        req.query.session,
        req.body.CallSid,
        req.query.turn,
        req.body.SpeechResult ?? "",
      );
      res.type("text/xml").send(provider.render(r, req.query.session));
    } catch {
      res.type("text/xml").send(
        provider.render(
          {
            text: "This call session is unavailable. Please use Telegram.",
            end: true,
            turn: "",
          },
          "",
        ),
      );
    }
  });
  app.post("/voice/status", async (req, res) => {
    if (
      ["completed", "busy", "failed", "no-answer", "canceled"].includes(
        req.body.CallStatus,
      )
    )
      await service.disconnect(req.body.CallSid);
    res.sendStatus(204);
  });
  return app;
}
