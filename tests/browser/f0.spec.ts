import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Keep shipments moving." }),
  ).toBeVisible();
  await expect(page.getByText("23", { exact: true }).first()).toBeVisible();
});
test("overview, filters, evidence, sources, closed review boundary and replay polling", async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.getByRole("link", { name: "Explore cases" }).click();
  await expect(page.getByRole("heading", { name: "23 cases" })).toBeVisible();
  await page
    .getByLabel("Workflow", { exact: true })
    .selectOption("AWAITING_HUMAN");
  await expect(page.getByRole("heading", { name: "10 cases" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await page.getByLabel("Search cases").fill("manual override");
  await expect(
    page.getByRole("heading", { name: "1 case", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Gross weight · manual override applied" })
    .click();
  await expect(page.locator(".assessment").first()).toContainText(
    "Needs review",
  );
  await expect(page.locator(".assessment").nth(1)).toContainText("OK");
  await expect(page.getByText("Manual override · Ungrounded")).toBeVisible();
  await expect(page.locator(".comparison-row")).toHaveCount(7);
  await page.getByText("View evidence (1)", { exact: true }).first().click();
  await expect(
    page
      .locator(".comparison-row")
      .first()
      .locator(".field-value")
      .first()
      .getByText(
        "Shipper (Principal or Seller): Meridian Exports 10 Harbour Road Suite 08, Demo District",
        { exact: true },
      ),
  ).toBeVisible();
  const popupPromise = context.waitForEvent("page");
  await page.getByRole("link", { name: "Open source ↗" }).first().click();
  const popup = await popupPromise;
  await expect(popup.locator("body")).toContainText("SYNTHETIC DEMONSTRATION");
  await expect(popup.locator("body")).toContainText(
    "Gross Wt (kgs): 21,707 KG",
  );
  await popup.close();
  await expect(
    page.getByRole("button", { name: "Preview value" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Replay / Reprocess" }).click();
  await expect(
    page.getByText("Synthetic processing in progress."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview value" })).toBeEnabled(
    { timeout: 15000 },
  );
  await expect(page.locator(".assessment").first()).toContainText(
    "Needs review",
  );
  await expect(page.locator(".assessment").nth(1)).toContainText(
    "Needs review",
  );
  await expect(page.getByText("Manual override · Ungrounded")).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("every fixture is reachable with correct review modes, failures and history", async ({
  page,
}) => {
  const states = [
    "grounded-input",
    "both-sides",
    "mismatch-review",
    "unsupported-candidate",
    "resume-failure",
    "processing",
    "match",
    "mismatch",
    "non-bl",
    "field-input",
    "candidate-choice",
    "document-choice",
    "blocked-open",
    "blocked-acknowledged",
    "human-resolved",
    "document-confirmed",
    "sequential-first",
    "sequential-second",
    "failed-before",
    "failed-after",
    "accepted-processing",
    "superseded",
    "no-attachment-intent",
  ];
  for (const id of states) {
    await page.goto(`/cases/demo_${id}`);
    await expect(page.locator(".detail-heading h1")).toBeVisible();
    await expect(page.getByText("API data failed Shared Contract")).toHaveCount(
      0,
    );
    if (!["processing", "non-bl", "failed-before", "superseded"].includes(id))
      await expect(page.locator(".comparison-row")).toHaveCount(7);
    if (id === "candidate-choice" || id === "document-choice")
      await expect(
        page.getByRole("button", { name: "None of these" }),
      ).toBeEnabled();
    if (id === "blocked-acknowledged") {
      await expect(
        page.getByText("Acknowledgment recorded", { exact: true }),
      ).toBeVisible();
      await expect(page.locator(".run-strip")).toContainText("External block");
    }
    if (id === "failed-after")
      await expect(
        page.getByText("Accepted decision retained.", { exact: true }),
      ).toBeVisible();
    if (id === "superseded")
      await expect(
        page.getByText(
          "Old review superseded. Replies cannot affect the new run.",
        ),
      ).toBeVisible();
  }
});
test("empty/reset, explicit advance, slow loading, errors and recovery", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Demo controls" }).click();
  await page.getByRole("button", { name: "Load empty dataset" }).click();
  await expect(
    page.getByRole("heading", { name: "No pending decisions" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Explore cases" }).click();
  await expect(page.getByRole("heading", { name: "0 cases" })).toBeVisible();
  await page.getByRole("button", { name: "Process sample email" }).click();
  await expect(
    page.getByText("Synthetic processing in progress."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Advance processing" }).click();
  await expect(page.locator(".run-strip")).toContainText("Completed");
  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByText("23", { exact: true }).first()).toBeVisible();
  await page.getByLabel("Connection", { exact: true }).selectOption("slow");
  await expect(page.getByText("Loading current API data…")).toBeVisible();
  await expect(page.getByText("23", { exact: true }).first()).toBeVisible();
  await page.getByLabel("Connection", { exact: true }).selectOption("outage");
  await expect(page.getByRole("alert")).toContainText(
    "Simulated service outage",
  );
  await page.getByLabel("Connection", { exact: true }).selectOption("denied");
  await expect(page.getByRole("alert")).toContainText(
    "Simulated access denied",
  );
  await page.reload();
  await page.getByRole("button", { name: "Demo controls" }).click();
  await expect(page.getByLabel("Connection", { exact: true })).toHaveValue(
    "denied",
  );
  await page.getByLabel("Connection", { exact: true }).selectOption("none");
  await expect(page.getByText("23", { exact: true }).first()).toBeVisible();
  await page.goto("/cases/unavailable");
  await expect(page.getByRole("alert")).toContainText("Case unavailable");
});
for (const width of [375, 768, 1024, 1440])
  test(`responsive and accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/cases", "/cases/demo_candidate-choice"]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.locator(".loading")).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/screenshots/${width}-${path === "/" ? "overview" : path === "/cases" ? "cases" : "detail"}.png`,
        fullPage: true,
      });
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => n.target),
        })),
      ).toEqual([]);
    }
  });
test("poll failure retains stale data; recovery does not regress current run", async ({
  page,
}) => {
  await page.route("**/api/v1/stats", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "INTERNAL", message: "Test service interruption" },
      }),
    }),
  );
  await expect(page.getByRole("alert")).toContainText("showing stale data", {
    timeout: 8000,
  });
  await expect(page.getByText("23", { exact: true }).first()).toBeVisible();
  await page.unroute("**/api/v1/stats");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("keyboard access, reduced motion and combined API filters", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  await page.getByRole("link", { name: "Explore cases" }).click();
  const requests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/cases?")) requests.push(r.url());
  });
  await page
    .getByLabel("Category", { exact: true })
    .selectOption("BL_COMPARISON");
  await page
    .getByLabel("Operational outcome", { exact: true })
    .selectOption("MISMATCH");
  await page.getByLabel("Review state", { exact: true }).selectOption("false");
  await expect(
    page.getByRole("heading", { name: "1 case", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Container quantity differs" }),
  ).toBeVisible();
  expect(
    requests.some(
      (url) =>
        url.includes("category=BL_COMPARISON") &&
        url.includes("final_status=MISMATCH") &&
        url.includes("has_open_review=false"),
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "Container quantity differs" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("External correction required", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".review-panel")).toHaveCount(0);
  await expect(page.locator(".comparison-row")).toHaveCount(7);
  await page
    .locator(".comparison-row")
    .first()
    .getByText("View evidence (1)", { exact: true })
    .first()
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.locator(".comparison-row").first().locator("blockquote").first(),
  ).toBeVisible();
});

test("participant-shaped synthetic context, fictional receipt time and unresolved no-attachment intent", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto("/cases/demo_match");
  await expect(page.getByText(/Fictional fixture receipt time:/)).toBeVisible();
  await expect(
    page.getByText("Participant receipt time is unavailable.", { exact: true }),
  ).toBeVisible();
  await page.getByText("Read synthetic email body", { exact: true }).click();
  await expect(page.getByLabel("Synthetic email body")).toContainText(
    "3X40'HC",
  );
  await expect(page.getByLabel("Synthetic email body")).toContainText(
    "GROSS WT: 21,707 KG",
  );
  await page
    .getByText("Inspect participant-shaped source record", { exact: true })
    .click();
  const source = JSON.parse(
    await page.getByLabel("Synthetic source record").innerText(),
  );
  expect(Object.keys(source).sort()).toEqual([
    "attachments",
    "body",
    "email_id",
    "from",
    "subject",
  ]);
  expect(source.attachments).toHaveLength(2);
  expect(source).not.toHaveProperty("received_at");
  const shipper = page.locator(".comparison-row").filter({
    has: page.getByRole("heading", { name: "Shipper", exact: true }),
  });
  await expect(shipper.locator(".field-value > strong").first()).toContainText(
    "Suite 08, Demo District",
  );
  await expect(shipper.locator(".field-value > strong").first()).toHaveCSS(
    "white-space",
    "pre-line",
  );
  await expect(
    page.locator(".comparison-row").filter({
      has: page.getByRole("heading", {
        name: "Container count",
        exact: true,
      }),
    }),
  ).toContainText("3 x 40'HC");
  await expect(
    page.locator(".comparison-row").filter({
      has: page.getByRole("heading", {
        name: "Gross weight (kg)",
        exact: true,
      }),
    }),
  ).toContainText("21707.00 kgs");
  await page.setViewportSize({ width: 375, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/screenshots/participant-context-375.png",
    fullPage: true,
  });
  await page.goto("/cases/demo_no-attachment-intent");
  await expect(
    page.getByText("No-attachment intent remains unresolved", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".run-strip")).toContainText("External block");
  await expect(page.locator(".run-strip")).toContainText("BL comparison");
  await expect(page.locator(".assessment").first()).toContainText(
    "Needs review",
  );
  await expect(
    page.getByRole("heading", { name: "No documents available" }),
  ).toBeVisible();
  await expect(page.locator(".comparison-row")).toHaveCount(7);
  await expect(
    page.locator(".field-value > strong").filter({ hasText: "Unknown" }),
  ).toHaveCount(14);
  expect(errors).toEqual([]);
});

test("v2.1.1 known and unknown receipt times remain separate from system activity through replay", async ({
  page,
}) => {
  for (const id of ["processing", "mismatch", "match", "accepted-processing"]) {
    await page.goto(`/cases/demo_${id}`);
    await expect(page.getByText(/Case created:/)).toBeVisible();
    await expect(page.getByText(/Case created:/)).toContainText(
      "Last updated:",
    );
    if (["processing", "mismatch"].includes(id)) {
      await expect(page.getByText(/Received time unavailable/)).toBeVisible();
    } else
      await expect(
        page.getByText(/Fictional fixture receipt time:/),
      ).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Invalid Date");
  }
  await page.goto("/cases/demo_mismatch");
  const before = await (
    await page.request.get("/api/v1/cases/demo_mismatch")
  ).json();
  await page.getByRole("button", { name: "Replay / Reprocess" }).click();
  await expect(page.locator(".run-strip")).toContainText("Processing");
  await expect(page.getByText(/Received time unavailable/)).toBeVisible();
  await expect(page.locator(".run-strip")).toContainText("Completed", {
    timeout: 15000,
  });
  const after = await (
    await page.request.get("/api/v1/cases/demo_mismatch")
  ).json();
  expect(after.email.received_at).toBeNull();
  expect(after.created_at).toBe(before.created_at);
  expect(after.run.started_at).not.toBe(before.run.started_at);
  expect(after.schema_version).toBe("2.1.1");
  await expect(page.getByText(/Received time unavailable/)).toBeVisible();
});
