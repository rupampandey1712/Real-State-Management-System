import { expect, test } from "@playwright/test";

import { anyListingId, expectNoA11yViolations } from "./helpers";

// NFR-6: WCAG 2.1 AA on the main pages, checked with axe in every browser of the matrix.

test("home page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoA11yViolations(page, "home");
});

test("search results with filter panel open", async ({ page }) => {
  await page.goto("/search?city=Pune");
  await expect(page.getByText(/homes/).first()).toBeVisible();
  await page.getByRole("button", { name: "Filters" }).click();
  await expect(page.getByRole("heading", { name: "Filters" })).toBeVisible();
  await expectNoA11yViolations(page, "search + filters");
});

test("listing page with the Q&A panel", async ({ page, request }) => {
  const id = await anyListingId(request);
  await page.goto(`/listings/${id}`);
  await expect(page.getByRole("heading", { name: "Ask about this home" })).toBeVisible();
  await expectNoA11yViolations(page, "listing detail");
});

test("sign-in and privacy pages", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expectNoA11yViolations(page, "login");
  await page.goto("/privacy");
  await expectNoA11yViolations(page, "privacy");
});

test("keyboard users can skip to content and search", async ({ page, browserName, isMobile }) => {
  test.skip(isMobile, "no hardware keyboard");
  test.skip(browserName === "webkit", "Safari skips links on Tab unless 'Press Tab to highlight each item' is on");
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.getByRole("textbox", { name: "Describe the home you want" }).focus();
  await page.keyboard.type("2 BHK in Pune");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/search\?q=2/);
});
