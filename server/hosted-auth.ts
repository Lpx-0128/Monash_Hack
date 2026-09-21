import express from "express";
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync, renameSync } from "node:fs";
import { dirname } from "node:path";
import { z } from "zod";

export function hostedAuth(file: string, secret: string, origin: string, secure = true) {
  if (secret.length < 32) throw new Error("Dashboard link secret too short");
  const schema = z.object({ used: z.record(z.string(), z.number()), sessions: z.record(z.string(), z.object({ actor: z.string(), expires: z.number() })) });
  let state = existsSync(file) ? schema.parse(JSON.parse(readFileSync(file, "utf8"))) : { used: {}, sessions: {} } as z.infer<typeof schema>;
  const save = () => {
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file + ".tmp", JSON.stringify(state), { mode: 0o600 });
    renameSync(file + ".tmp", file);
  };
  const hash = (v: string) => createHash("sha256").update(v).digest("hex");
  const router = express.Router();
  router.use(express.json({ limit: "16kb" }));
  router.use((req, res, next) => {
    res.setHeader("Referrer-Policy", "no-referrer");
    if (req.path.startsWith("/api") && !["GET", "HEAD"].includes(req.method) && !req.headers.authorization && req.headers.origin !== origin)
      return res.status(403).json({ error: { code: "FORBIDDEN", message: "Same-origin request required." } });
    const cookie = (req.headers.cookie ?? "").split(";").map(s => s.trim()).find(s => s.startsWith("harbor_session="))?.slice(15);
    const session = cookie ? state.sessions[hash(cookie)] : undefined;
    res.locals.hostedActor = session && session.expires > Date.now() ? session.actor : "sample";
    next();
  });
  router.post("/api/session/exchange", (req, res) => {
    try {
      const token = z.string().max(2000).parse(req.body.token);
      const parts = token.split(".");
      if (parts.length !== 2) throw new Error();
      const expected = createHmac("sha256", secret).update(parts[0]).digest();
      const signature = Buffer.from(parts[1], "base64url");
      if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) throw new Error();
      const data = z.strictObject({ actor: z.string().regex(/^\d{1,20}$/), path: z.string().max(500), expires: z.number(), nonce: z.string() }).parse(JSON.parse(Buffer.from(parts[0], "base64url").toString()));
      if (data.expires < Date.now() || data.expires > Date.now() + 300000 || state.used[data.nonce]) throw new Error();
      if (!/^\/(?:cases(?:\/[A-Za-z0-9_-]+)?(?:\?has_open_review=true)?)?$/.test(data.path)) throw new Error();
      const before = structuredClone(state);
      const session = randomBytes(32).toString("hex");
      // Keep a bounded number of browser sessions per identity.
      const oldSessions = Object.entries(state.sessions).filter(([, s]) => s.actor === data.actor).sort((a,b) => a[1].expires - b[1].expires);
      for (const [key] of oldSessions.slice(0, Math.max(0, oldSessions.length - 9))) delete state.sessions[key];
      state.used[data.nonce] = data.expires;
      state.sessions[hash(session)] = { actor: data.actor, expires: Date.now() + 30 * 86400000 };
      state.used = Object.fromEntries(Object.entries(state.used).filter(([, t]) => t > Date.now()));
      state.sessions = Object.fromEntries(Object.entries(state.sessions).filter(([, s]) => s.expires > Date.now()));
      try { save(); } catch (error) { state = before; throw error; }
      res.cookie("harbor_session", session, { httpOnly: true, secure, sameSite: "strict", path: "/", maxAge: 30 * 86400000 });
      res.setHeader("Cache-Control", "no-store");
      res.json({ path: data.path });
    } catch {
      res.status(401).json({ error: { code: "UNAUTHORIZED", message: "Link expired or already used. Request a new dashboard link in Telegram." } });
    }
  });
  return router;
}
