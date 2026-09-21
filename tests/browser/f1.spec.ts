import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const review = (page: Page) => page.locator(".review-panel");
async function open(page: Page, id: string) {
  await page.goto(`/cases/demo_${id}`);
  await expect(review(page)).toBeVisible();
}
async function preview(page: Page, value: string) {
  await page
    .getByLabel(/^(SI|BL) (gross weight kg|container count)$/)
    .fill(value);
  await page.getByRole("button", { name: "Preview value" }).click();
  await expect(
    page.getByRole("region", { name: "Decision preview" }),
  ).toBeVisible();
}
async function confirm(page: Page) {
  await page
    .getByRole("button", { name: "Confirm submission", exact: true })
    .click();
}
async function settled(page: Page, status = "Completed") {
  await expect(page.locator(".run-strip")).toContainText(status, {
    timeout: 15000,
  });
}
async function advance(page: Page) {
  await page.request.post("/api/demo/advance", { data: {} });
}
test("grounded entry previews canonical value and waits for the timed backend result", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await open(page, "grounded-input");
  let posts = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/decision")) posts++;
  });
  await preview(page, "21707.00 kg");
  await expect(
    page.getByRole("region", { name: "Decision preview" }),
  ).toContainText("canonical value: 21707 kg");
  expect(posts).toBe(0);
  const response = page.waitForResponse((r) => r.url().endsWith("/decision"));
  await confirm(page);
  expect((await response).status()).toBe(202);
  await expect(page.locator(".run-strip")).toContainText("Processing");
  await expect(
    page.getByText("Last result; updating.", { exact: false }),
  ).toBeVisible();
  await expect(
    review(page).getByRole("button", { name: "Preview value" }),
  ).toBeDisabled();
  await settled(page);
  await expect(page.locator(".operational")).toContainText("OK");
  await expect(page.locator(".assessment").first()).toContainText(
    "Needs review",
  );
  await expect(
    page.getByText("Human document-confirmed · Grounded"),
  ).toBeVisible();
  expect(posts).toBe(1);
  expect(errors).toEqual([]);
});
test("invalid input, cancel and edit cannot reuse an old override confirmation", async ({
  page,
}) => {
  await open(page, "field-input");
  let posts = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/decision")) posts++;
  });
  await page.getByLabel("BL gross weight kg").fill("1,234");
  await page.getByRole("button", { name: "Preview value" }).click();
  await expect(page.getByRole("alert")).toContainText("without grouping");
  expect(posts).toBe(0);
  await preview(page, "22000");
  await confirm(page);
  await expect(
    page.getByRole("button", { name: "Confirm manual override" }),
  ).toBeVisible();
  await expect(review(page)).toContainText("ungrounded manual override");
  await page.getByRole("button", { name: "Cancel proposal" }).click();
  await expect(
    page.getByRole("button", { name: "Confirm manual override" }),
  ).toHaveCount(0);
  await preview(page, "22000");
  await confirm(page);
  await expect(
    page.getByRole("button", { name: "Confirm manual override" }),
  ).toBeVisible();
  await page.getByLabel("BL gross weight kg").fill("21707");
  await expect(
    page.getByRole("button", { name: "Confirm manual override" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Preview value" }).click();
  await confirm(page);
  await expect(
    page.getByRole("button", { name: "Confirm manual override" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirm manual override" }).click();
  await advance(page);
  await settled(page);
  await expect(page.getByText("Manual override · Ungrounded")).toBeVisible();
  await expect(page.locator(".operational")).toContainText("OK");
  const c = await (
    await page.request.get("/api/v1/cases/demo_field-input")
  ).json();
  expect(c.fields[6].bl.override_confirmations[0].proposed_value).toBe(21707);
  expect(c.machine_assessment.status).toBe("NEEDS_REVIEW");
  expect(posts).toBe(4);
});
test("candidate values, unsupported candidate and explicit document role work end to end", async ({
  page,
}) => {
  for (const [id, label] of [
    ["candidate-choice", "21707 kg · original line"],
    ["unsupported-candidate", "23000 kg · unsupported proposal"],
    ["document-choice", null],
  ] as const) {
    await open(page, id);
    if (label)
      await review(page)
        .getByRole("button", { name: label, exact: true })
        .click();
    else {
      await expect(review(page)).toContainText("Target document role: BL");
      await review(page)
        .getByRole("button")
        .filter({ hasText: /synthetic-document-choice-BL/ })
        .click();
    }
    await confirm(page);
    if (id === "unsupported-candidate") {
      await expect(
        page.getByRole("button", { name: "Confirm manual override" }),
      ).toBeVisible();
      await page
        .getByRole("button", { name: "Confirm manual override" })
        .click();
    }
    await advance(page);
    await settled(page);
    await expect(page.locator(".operational")).toContainText(
      id === "unsupported-candidate" ? "Mismatch" : "OK",
    );
  }
});
test("sequential SI then BL decisions never carry the first proposal into the second review", async ({
  page,
}) => {
  await open(page, "both-sides");
  await preview(page, "21707");
  await confirm(page);
  await advance(page);
  await expect(review(page)).toContainText("Target: BL", { timeout: 10000 });
  await expect(page.getByLabel("BL gross weight kg")).toHaveValue("");
  await expect(page.locator(".operational")).toContainText("Needs review");
  await preview(page, "21707");
  await confirm(page);
  await advance(page);
  await settled(page);
  await expect(page.locator(".operational")).toContainText("OK");
  await expect(page.locator(".assessment").first()).toContainText(
    "Needs review",
  );
});
test("all escapes close reviews but leave external work; mismatch survives other uncertainty", async ({
  page,
}) => {
  for (const [id, button] of [
    ["blocked-open", "Acknowledge external action"],
    ["field-input", "I can’t tell"],
    ["candidate-choice", "None of these"],
  ]) {
    await open(page, id);
    await review(page)
      .getByRole("button", { name: button, exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Decision preview" }),
    ).toContainText("externally blocked");
    await confirm(page);
    await expect(page.locator(".run-strip")).toContainText("Processing");
    await advance(page);
    await settled(page, "External block");
    await expect(review(page)).toContainText("Closed: decision accepted");
  }
  await open(page, "mismatch-review");
  await expect(
    page.locator(".comparison-row").filter({ hasText: "Container count" }),
  ).toContainText("Mismatch");
  await preview(page, "21707");
  await confirm(page);
  await page.getByRole("button", { name: "Confirm manual override" }).click();
  await advance(page);
  await settled(page);
  await expect(
    page.getByText("External correction required", { exact: true }),
  ).toBeVisible();
});
test("lost response refetches accepted work without resubmitting; failure retains decision", async ({
  page,
}) => {
  await open(page, "grounded-input");
  await page.getByRole("button", { name: "Demo controls" }).click();
  await page
    .getByLabel("Next decision simulation")
    .selectOption("lost-response");
  await expect(
    page.getByText("Decision simulation updated.", { exact: true }),
  ).toBeVisible();
  let posts = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/decision")) posts++;
  });
  await preview(page, "21707");
  await confirm(page);
  await expect(page.locator(".run-strip")).toContainText("Processing");
  await settled(page);
  expect(posts).toBe(1);
  await open(page, "resume-failure");
  await preview(page, "21707");
  await confirm(page);
  await page.getByRole("button", { name: "Confirm manual override" }).click();
  await advance(page);
  await settled(page, "Failed");
  await expect(
    page.getByText("Accepted decision retained.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview value" }),
  ).toBeDisabled();
});
test("stale confirmation refetches a new run; draft does not leak into it", async ({
  page,
}) => {
  await open(page, "grounded-input");
  await preview(page, "21707");
  // Hold ordinary polls while another client in this session reprocesses the case.
  await page.route("**/api/v1/cases/demo_grounded-input", (route) =>
    route.request().method() === "GET" ? route.abort() : route.continue(),
  );
  await page.request.post("/api/v1/cases/demo_grounded-input/reprocess", {
    data: {},
  });
  const response = page.waitForResponse((r) => r.url().endsWith("/decision"));
  await confirm(page);
  expect((await response).status()).toBe(409);
  await expect(
    page.getByRole("button", { name: "Refetch decision status" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview value" }),
  ).toBeDisabled();
  await page.unroute("**/api/v1/cases/demo_grounded-input");
  await page.getByRole("button", { name: "Refetch decision status" }).click();
  await advance(page);
  await settled(page, "Awaiting human");
  await expect(page.getByLabel("BL gross weight kg")).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Confirm submission" }),
  ).toHaveCount(0);
});
test("uncertain unsent response preserves draft until refetch; authorization failure locks actions", async ({
  page,
}) => {
  await open(page, "grounded-input");
  await preview(page, "21707");
  await page.route("**/decision", (r) => r.abort());
  await confirm(page);
  await expect(
    page.getByText(/Refetch confirmed this review is still open/),
  ).toBeVisible();
  await expect(page.getByLabel("BL gross weight kg")).toHaveValue("21707");
  await expect(
    page.getByRole("button", { name: "Confirm submission" }),
  ).toHaveCount(0);
  await page.unroute("**/decision");
  await page.reload();
  await expect(page.getByLabel("BL gross weight kg")).toHaveValue("21707");
  await page.getByRole("button", { name: "Preview value" }).click();
  await page.request.post("/api/demo/fault", { data: { mode: "denied" } });
  await confirm(page);
  await expect(
    page.getByRole("button", { name: "Refetch decision status" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Preview value" }),
  ).toBeDisabled();
  await page.request.post("/api/demo/fault", { data: { mode: "none" } });
  await page.getByRole("button", { name: "Refetch decision status" }).click();
  await expect(page.getByLabel("BL gross weight kg")).toHaveValue("21707");
});
for (const width of [375, 768, 1440])
  test(`review confirmation accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await open(page, "field-input");
    await preview(page, "22000");
    await confirm(page);
    await expect(
      page.getByRole("button", { name: "Confirm manual override" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    await page.locator(".proposal").screenshot({
      path: `test-results/screenshots/f1-override-${width}.png`,
    });
    await page.getByRole("button", { name: "Cancel proposal" }).focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("button", { name: "Confirm manual override" }),
    ).toHaveCount(0);
  });
