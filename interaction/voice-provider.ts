import { createHmac, timingSafeEqual } from "node:crypto";

export type VoiceReply = {
  text: string;
  end?: boolean;
  turn: string;
  waitSeconds?: number;
};
export type ProviderDiagnostic = {
  kind: "http" | "network" | "timeout" | "invalid_response" | "unknown";
  httpStatus?: number;
  providerCode?: number;
  trialParameterRestriction?: boolean;
};
export class VoiceProviderError extends Error {
  constructor(public diagnostic: ProviderDiagnostic) {
    super("Voice provider request failed");
  }
}
export const providerDiagnostic = (error: unknown): ProviderDiagnostic =>
  error instanceof VoiceProviderError ? error.diagnostic : { kind: "unknown" };
export interface VoiceProvider {
  readonly applicationDeadlineOnly?: boolean;
  validateCapability?(url: string): boolean;
  validateInboundCapability?(url: string): boolean;
  verifyInbound?(call: string, phone: string): Promise<boolean>;
  start(phone: string, session: string, seconds: number): Promise<string>;
  end(call: string): Promise<void>;
  limit(call: string, seconds: number): Promise<void>;
  validate(
    url: string,
    fields: Record<string, string>,
    signature: string,
  ): boolean;
  render(reply: VoiceReply, session: string): string;
}
const xml = (v: string) =>
  v.replace(
    /[<>&"']/g,
    (c) =>
      ({
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
      })[c]!,
  );

/** Provider credentials, signatures, identifiers and TwiML stay in this adapter. */
export class TwilioProvider implements VoiceProvider {
  constructor(
    private account: string,
    private token: string,
    private from: string,
    public origin: string,
    private mode: "standard" | "trial" | "trial-demo" = "standard",
    private callbackLifetimeSeconds = 180,
    private inboundKey?: string,
  ) {
    if (
      inboundKey &&
      (mode !== "trial-demo" || !/^[a-f0-9]{64}$/.test(inboundKey))
    )
      throw new Error(
        "Inbound demo requires a separate random 32-byte key and trial-demo mode",
      );
    if (
      !Number.isInteger(callbackLifetimeSeconds) ||
      callbackLifetimeSeconds < 30 ||
      callbackLifetimeSeconds > (mode === "trial-demo" ? 600 : 180)
    )
      throw new Error("Invalid callback lifetime");
    if (
      new URL(origin).protocol !== "https:" ||
      new URL(origin).pathname !== "/"
    )
      throw new Error("VOICE_PUBLIC_URL must be an HTTPS origin");
    this.origin = origin.replace(/\/$/, "");
  }
  get applicationDeadlineOnly() {
    return this.mode === "trial-demo";
  }
  inboundUrl(expires = Date.now() + 3600000) {
    if (!this.inboundKey) throw new Error("Inbound demo is disabled");
    const url = new URL(`/voice/inbound/${expires}`, this.origin);
    const capability = createHmac("sha256", this.inboundKey)
        .update("harbor-trial-inbound:" + url.href)
        .digest("hex");
    return `${url.href}/${capability}`;
  }
  validateInboundCapability(url: string) {
    if (!this.inboundKey) return false;
    const parsed = new URL(url);
    const match = /^\/voice\/inbound\/(\d{13})\/([a-f0-9]{64})$/.exec(parsed.pathname);
    if (parsed.origin !== this.origin || !match || parsed.search || parsed.hash)
      return false;
    const expires = Number(match[1]);
    if (
      !Number.isSafeInteger(expires) ||
      expires <= Date.now() ||
      expires > Date.now() + 3600000
    )
      return false;
    const expected = this.inboundUrl(expires).split("/").at(-1)!;
    const supplied = match[2];
    return (
      /^[a-f0-9]{64}$/.test(supplied) &&
      timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
    );
  }
  async verifyInbound(call: string, phone: string) {
    if (!this.inboundKey || !/^CA[a-f0-9]{32}$/i.test(call)) return false;
    try {
      const r = await fetch(
        `https://api.twilio.com/2010-04-01/Accounts/${this.account}/Calls/${call}.json`,
        {
          headers: {
            Authorization: `Basic ${Buffer.from(this.account + ":" + this.token).toString("base64")}`,
          },
          signal: AbortSignal.timeout(3000),
          redirect: "error",
        },
      );
      if (!r.ok) return false;
      const c = await r.json();
      return (
        c.sid === call &&
        c.account_sid === this.account &&
        c.direction === "inbound" &&
        c.from === phone &&
        c.to === this.from &&
        ["ringing", "in-progress"].includes(c.status)
      );
    } catch {
      return false;
    }
  }
  private callback(path: string, session: string, turn?: string) {
    const url = new URL(path, this.origin);
    url.searchParams.set("session", session);
    if (turn) url.searchParams.set("turn", turn);
    if (this.mode === "trial-demo") {
      url.searchParams.set(
        "expires",
        String(Date.now() + this.callbackLifetimeSeconds * 1000),
      );
      const mac = createHmac("sha256", this.token)
        .update("harbor-trial-demo:" + url.href)
        .digest("hex");
      url.searchParams.set("cap", mac);
    }
    return url.href;
  }
  validateCapability(url: string) {
    if (this.mode !== "trial-demo") return false;
    const parsed = new URL(url);
    if (
      parsed.origin !== this.origin ||
      !["/voice/start", "/voice/turn"].includes(parsed.pathname)
    )
      return false;
    const keys = [...parsed.searchParams.keys()];
    const allowed =
      parsed.pathname === "/voice/start"
        ? ["session", "expires", "cap"]
        : ["session", "turn", "expires", "cap"];
    if (
      keys.length !== allowed.length ||
      new Set(keys).size !== keys.length ||
      keys.some((k) => !allowed.includes(k))
    )
      return false;
    if (
      !/^[a-f0-9]{32}$/.test(parsed.searchParams.get("session") ?? "") ||
      (parsed.pathname === "/voice/turn" &&
        !/^[a-f0-9]{32}$/.test(parsed.searchParams.get("turn") ?? ""))
    )
      return false;
    const expiry = Number(parsed.searchParams.get("expires"));
    if (
      !Number.isSafeInteger(expiry) ||
      expiry <= Date.now() ||
      expiry > Date.now() + this.callbackLifetimeSeconds * 1000
    )
      return false;
    const supplied = parsed.searchParams.get("cap") ?? "";
    parsed.searchParams.delete("cap");
    const expected = createHmac("sha256", this.token)
      .update("harbor-trial-demo:" + parsed.href)
      .digest("hex");
    return (
      /^[a-f0-9]{64}$/.test(supplied) &&
      timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
    );
  }
  validate(url: string, fields: Record<string, string>, signature: string) {
    const value =
      url +
      Object.keys(fields)
        .sort()
        .map((k) => k + fields[k])
        .join("");
    const expected = createHmac("sha1", this.token)
      .update(value)
      .digest("base64");
    const suppliedBytes = Buffer.from(signature),
      expectedBytes = Buffer.from(expected);
    return (
      suppliedBytes.length === expectedBytes.length &&
      timingSafeEqual(suppliedBytes, expectedBytes)
    );
  }
  private async post(path: string, fields: Record<string, string>) {
    let r: Response;
    try {
      r = await fetch(
        `https://api.twilio.com/2010-04-01/Accounts/${this.account}/Calls${path}.json`,
        {
          method: "POST",
          redirect: "error",
          signal: AbortSignal.timeout(10000),
          headers: {
            Authorization: `Basic ${Buffer.from(this.account + ":" + this.token).toString("base64")}`,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams(fields),
        },
      );
    } catch (error) {
      throw new VoiceProviderError({
        kind:
          error instanceof Error &&
          ["TimeoutError", "AbortError"].includes(error.name)
            ? "timeout"
            : "network",
      });
    }
    let body: { sid?: unknown; code?: unknown; message?: unknown };
    try {
      body = await r.json();
    } catch {
      throw new VoiceProviderError({
        kind: "invalid_response",
        httpStatus: r.status,
      });
    }
    if (!r.ok)
      throw new VoiceProviderError({
        kind: "http",
        httpStatus: r.status,
        ...(typeof body.code === "number" && Number.isSafeInteger(body.code)
          ? { providerCode: body.code }
          : {}),
        ...(typeof body.message === "string" &&
        body.message.includes("trial accounts have limited parameter access")
          ? { trialParameterRestriction: true }
          : {}),
      });
    if (typeof body.sid !== "string" || !/^CA[0-9a-f]{32}$/i.test(body.sid))
      throw new VoiceProviderError({
        kind: "invalid_response",
        httpStatus: r.status,
      });
    return { sid: body.sid };
  }
  async start(phone: string, session: string, seconds: number) {
    const r = await this.post("", {
      To: phone,
      From: this.from,
      Url: this.callback("/voice/start", session),
      StatusCallback: `${this.origin}/voice/status`,
      ...(this.mode === "standard"
        ? {
            Method: "POST",
            StatusCallbackMethod: "POST",
            TimeLimit: String(seconds),
            Timeout: "20",
          }
        : {}),
    });
    return r.sid;
  }
  async end(call: string) {
    if (this.applicationDeadlineOnly) return;
    await this.post("/" + encodeURIComponent(call), { Status: "completed" });
  }
  async limit(call: string, seconds: number) {
    if (this.applicationDeadlineOnly) return;
    await this.post("/" + encodeURIComponent(call), {
      TimeLimit: String(seconds),
    });
  }
  render(r: VoiceReply, session: string) {
    const wait = r.waitSeconds === 20 ? 20 : r.waitSeconds === 10 ? 10 : 4;
    const speak = (text: string) =>
      `<Say voice="Polly.Joanna-Neural" language="en-US">${xml(text)}</Say>`;
    const challenge =
      r.waitSeconds === 20
        ? /then ([\d ]+) in/.exec(r.text)?.[1].replaceAll(" ", "")
        : undefined;
    const words = [
      "zero",
      "one",
      "two",
      "three",
      "four",
      "five",
      "six",
      "seven",
      "eight",
      "nine",
    ];
    const digits =
      challenge && /^\d{6}$/.test(challenge)
        ? [...challenge]
            .map((d) => speak(words[Number(d)]) + '<Pause length="1"/>')
            .join("")
        : undefined;
    const say = digits
      ? speak(
          "Harbor synthetic demo. To authenticate, open Telegram. Type slash voice, a space, then these six digits.",
        ) +
        digits +
        speak("Again.") +
        digits +
        speak(
          "Send that message in your enrolled bot chat. I will wait. Then say ready.",
        )
      : speak(r.text);
    return `<?xml version="1.0" encoding="UTF-8"?><Response>${
      r.end
        ? say + "<Hangup/>"
        : `<Gather input="speech" language="en-US" hints="ready, review one, review two, review three, I have checked, Alpha, Bravo, Charlie, option A, option B, option C, yes, no, repeat, status, not now" timeout="${wait}" speechTimeout="2" actionOnEmptyResult="true" method="POST" action="${xml(this.callback("/voice/turn", session, r.turn))}">${say}</Gather><Hangup/>`
    }</Response>`;
  }
}
