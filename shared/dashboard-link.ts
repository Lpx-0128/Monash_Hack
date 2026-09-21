import { createHmac, randomBytes } from "node:crypto";

export function dashboardLink(origin: string, actor: string, path = "/", secret = process.env.HARBOR_LINK_SECRET) {
  if (!secret || secret.length < 32) throw new Error("Dashboard link secret missing");
  const payload = Buffer.from(JSON.stringify({ actor, path, expires: Date.now() + 300000, nonce: randomBytes(24).toString("hex") })).toString("base64url");
  const signature = createHmac("sha256", secret).update(payload).digest("base64url");
  return `${new URL(origin).origin}/connect#${payload}.${signature}`;
}
