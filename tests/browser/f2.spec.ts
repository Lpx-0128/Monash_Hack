import { test, expect } from "@playwright/test";
import express from "express";
import path from "node:path";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import type { AddressInfo } from "node:net";
import { createApp } from "../../server/app";
import { ReviewApi } from "../../interaction/api";
import { ReviewEngine, type Button } from "../../interaction/engine";
test("F2 routed Telegram transport double → real API → processing and dashboard outcome", async ({
  page,
}) => {
  const token = "browser-test-service-token-00000000000",
    dir = mkdtempSync(path.join(tmpdir(), "f2-browser-"));
  const app = createApp({ interaction: { token, actors: ["101"] } });
  app.app.use(express.static(path.resolve("dist")));
  app.app.get("/{*path}", (_req, res) =>
    res.sendFile(path.resolve("dist/index.html")),
  );
  const server = app.app.listen(0, "127.0.0.1");
  await new Promise<void>((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const messages: { id: string; text: string; buttons: Button[][] }[] = [],
    errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    const api = new ReviewApi(base, token, "101"),
      engine = new ReviewEngine(
        path.join(dir, "state.json"),
        [{ actor: "101", chat: "101" }],
        () => api,
        {
          async send(_chat, text, buttons = []) {
            const id = String(messages.length + 1);
            messages.push({ id, text, buttons });
            return id;
          },
          async document() {
            return "document-test";
          },
        },
        base,
      );
    await page.goto(base + "/cases/demo_grounded-input");
    await expect(page.locator("footer")).toContainText("Shared synthetic demo");
    await expect(
      page.getByRole("heading", {
        name: "Source available · enter BL gross weight",
        exact: false,
      }),
    ).toBeVisible();
    const c = await api.get("demo_grounded-input"),
      b = engine.binding(c, { actor: "101", chat: "101" }),
      d = {
        message: undefined as string | undefined,
        ...b,
        key: "test",
        type: "review" as const,
        attempts: 0,
        due: 0,
        documents: {},
        documentAttempts: 0,
        documentDue: 0,
      };
    await engine.deliver(d, c);
    await engine.inbound({
      id: "1",
      actor: "101",
      chat: "101",
      message: "incoming",
      reply: d.message,
      text: "21707",
    });
    const proposal = messages.at(-1)!;
    await engine.inbound({
      id: "2",
      actor: "101",
      chat: "101",
      message: proposal.id,
      callback: proposal.buttons[0][0].callback_data,
    });
    await page.reload();
    await expect(
      page.getByText("Processing", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("Completed", { exact: true }).first(),
    ).toBeVisible({ timeout: 12000 });
    await expect(
      page.getByText("Human document-confirmed", { exact: false }).first(),
    ).toBeVisible();
    const result = await api.get(c.case_id);
    expect(result.resolution?.channel).toBe("TELEGRAM");
    expect(result.machine_assessment?.status).toBe("NEEDS_REVIEW");
    expect(result.resolution?.final_status).toBe("OK");
    expect(errors).toEqual([]);
    await page.screenshot({
      path: "test-results/screenshots/f2-simulator-dashboard.png",
      fullPage: true,
    });
  } finally {
    app.dispose();
    await new Promise<void>((r) => server.close(() => r()));
    rmSync(dir, { recursive: true, force: true });
  }
});
