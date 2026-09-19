import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { CaseSummary } from "../../shared/types";

test("overview filters retain all cases and use actual case state", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Shipment overview" }),
  ).toBeVisible();
  await expect(page.locator(".case-row")).toHaveCount(23);
  const response = await page.request.get("/api/v1/cases");
  const body: CaseSummary[] = await response.json();
  // The overview and existing API share the same current-run data.
  expect(response.ok()).toBe(true);
  await page.getByRole("button", { name: /^Needs input/ }).click();
  await expect(page.locator(".case-row")).toHaveCount(
    body.filter((c) => c.has_open_review).length,
  );
  await expect(page.locator(".case-row").first()).toContainText("Open review");
  await page.getByRole("button", { name: /^Matched/ }).click();
  await expect(page.locator(".case-row")).toHaveCount(
    body.filter(
      (c) =>
        c.category === "BL_COMPARISON" &&
        c.final_status === "OK" &&
        c.workflow_status === "COMPLETED",
    ).length,
  );
  for (const row of await page.locator(".case-row").all()) {
    await expect(row).toContainText("BL comparison");
    await expect(row).toContainText("Completed");
  }
  await page.getByRole("button", { name: /^Discrepancies/ }).click();
  await expect(page.locator(".case-row")).toHaveCount(
    body.filter((c) => c.final_status === "MISMATCH" || c.mismatch_count > 0)
      .length,
  );
  await expect(
    page.getByRole("link", {
      name: "Known container mismatch · weight review",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^All cases/ }).click();
  await page.getByLabel("Email category").selectOption("INVOICE_QUERY");
  await expect(page.locator(".case-row")).toHaveCount(1);
  await expect(page.locator(".case-row")).toContainText("Invoice enquiry");
  await page.getByLabel("Email category").selectOption("");
  await page.getByLabel("Search overview").fill("Container quantity differs");
  await expect(page.locator(".case-row")).toHaveCount(1);
  await page.getByRole("link", { name: "Container quantity differs" }).click();
  await expect(page.locator(".comparison-row:visible")).toHaveCount(1);
  await expect(page.locator(".comparison-row:visible")).toContainText(
    "Container count",
  );
  await page.locator(".matched-fields > summary").click();
  await expect(page.locator(".comparison-row:visible")).toHaveCount(7);
});

test("progress differentiates processing, external blocks and failures", async ({
  page,
}) => {
  for (const [id, text] of [
    ["processing", "Processing"],
    ["blocked-acknowledged", "Awaiting external source"],
    ["failed-before", "Processing failed"],
    ["accepted-processing", "Resuming after decision"],
    ["mismatch", "Correction required"],
  ]) {
    await page.goto(`/cases/demo_${id}`);
    await expect(page.locator(".progress-heading strong")).toHaveText(text);
    await expect(
      page.locator(".progress-stages [aria-current=step]"),
    ).toHaveCount(1);
  }
  await page.goto("/cases/demo_processing");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".current .stage-icon")).toHaveCSS(
    "animation-name",
    "none",
  );
});

for (const width of [375, 768, 1440])
  test(`warm theme contrast and layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of ["/", "/cases", "/cases/demo_candidate-choice"]) {
      await page.goto(path);
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.locator(".loading")).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        result.violations.map((v) => ({
          id: v.id,
          count: v.nodes.length,
          nodes: v.nodes
            .slice(0, 3)
            .map((n) => ({ target: n.target, summary: n.failureSummary })),
        })),
      ).toEqual([]);
      await page.screenshot({
        path: `test-results/refinement-${width}-${path === "/" ? "overview" : path === "/cases" ? "cases" : "review"}.png`,
        fullPage: true,
      });
    }
  });
