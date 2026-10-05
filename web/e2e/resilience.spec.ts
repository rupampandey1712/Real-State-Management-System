import { expect, test } from "@playwright/test";

import { anyListingId } from "./helpers";

// The map is an enhancement (ADR-0018): without WebGL (old devices, locked-down browsers, headless CI) or if its
// code fails to load, the page around it must keep working.
test.describe("without WebGL", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      // @ts-expect-error -- narrowing the overloads isn't useful in a test stub
      HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
        return type.startsWith("webgl") ? null : original.call(this, type, ...(args as []));
      };
    });
  });

  test("listing page still shows facts, Q&A and the enquiry form", async ({ page, request }) => {
    const id = await anyListingId(request);
    await page.goto(`/listings/${id}`);
    await expect(page.getByText("Carpet area")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ask about this home" })).toBeVisible();
    await expect(page.getByText(/The map couldn't load/)).toBeVisible();
  });

  test("search map view falls back to the list", async ({ page }) => {
    await page.goto("/search?city=Pune&view=map");
    await expect(page.getByText(/The map couldn't load/)).toBeVisible();
    await expect(page.locator("a[href^='/listings/']").first()).toBeVisible();
  });
});
