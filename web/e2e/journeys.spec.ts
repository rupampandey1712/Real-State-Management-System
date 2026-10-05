import { expect, test } from "@playwright/test";

import { anyListingId, hasWebGL } from "./helpers";

// The requirements' user journeys and FR-2 browse features, in every browser of the matrix (NFR-11).

test("J1: natural-language search → listing → cited answer → ask the agent", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Describe the home you want" }).fill("2 BHK in Pune under 1.5 crore");
  await page.getByRole("button", { name: "Find homes" }).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByRole("button", { name: /Remove “in Pune” from the search/ })).toBeVisible();

  await page.locator("a[href^='/listings/']").first().click();
  await expect(page.getByRole("heading", { name: "Ask about this home" })).toBeVisible();
  await expect(page.getByText("AI answers can be incomplete — verify with the agent.")).toBeVisible();

  await page.getByRole("textbox", { name: "Your question" }).fill("What is the monthly maintenance?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const source = page.getByRole("list", { name: "Sources" }).getByRole("button").first();
  await expect(source).toBeVisible({ timeout: 20_000 });
  await source.click(); // FR-5.2: citations open
  await expect(page.getByText(/From the listing:/)).toBeVisible();

  await page.getByRole("textbox", { name: "Your question" }).fill("Is there a temple nearby?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByRole("button", { name: "Ask the agent instead" }).click();
  await expect(page.locator("textarea[name='message']")).toHaveValue(/temple/);
});

test("FR-3.2: removing an AI chip re-runs a plain filter search", async ({ page }) => {
  await page.goto("/search?q=" + encodeURIComponent("2 BHK in Pune"));
  await page.getByRole("button", { name: /Remove “2 BHK” from the search/ }).click();
  await expect(page).toHaveURL(/city=Pune/);
  await expect(page).not.toHaveURL(/q=/);
});

test("FR-2.1/2.2/2.4: filters and sort live in the URL", async ({ page }) => {
  await page.goto("/search?city=Pune");
  await page.getByRole("button", { name: "Filters" }).click();
  await page.getByLabel("Buy or rent").selectOption("rent");
  await page.getByRole("button", { name: "Gym" }).click();
  await page.getByRole("button", { name: "Show homes" }).click();
  await expect(page).toHaveURL(/listing_type=rent/);
  await expect(page).toHaveURL(/amenities=gym/);
  await page.getByLabel("Sort").selectOption("price_asc");
  await expect(page).toHaveURL(/sort=price_asc/);
  // shareable: reloading the URL restores the same view
  await page.reload();
  await expect(page.getByLabel("Sort")).toHaveValue("price_asc");
});

test("FR-2.3: map view shows pins that open listings", async ({ page }) => {
  await page.goto("/search?city=Pune&view=map");
  test.skip(!(await hasWebGL(page)), "no WebGL in this browser — the fallback is covered by resilience.spec.ts");
  await expect(page.getByRole("region", { name: /Map of the homes/ })).toBeVisible();
  // the last pin in DOM order is drawn on top; dense localities overlap (clustering is a follow-up)
  const pin = page.getByRole("button", { name: /Open listing$/ }).last();
  await expect(pin).toBeVisible({ timeout: 20_000 });
  await pin.click();
  await expect(page).toHaveURL(/\/listings\//);
});

test("listing page shows facts, map pin and enquiry consent", async ({ page, request }) => {
  const id = await anyListingId(request);
  await page.goto(`/listings/${id}`);
  await expect(page.getByText("Carpet area")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /I agree to share my name/ })).toBeVisible();
  if (await hasWebGL(page)) {
    await expect(page.getByRole("region", { name: /Map showing the home's location/ })).toBeVisible();
  } else {
    await expect(page.getByText(/The map couldn't load/)).toBeVisible();
  }
});
