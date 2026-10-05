import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** WCAG 2.1 A + AA rules (NFR-6). The map canvas is third-party; the list is the accessible alternative. */
export async function expectNoA11yViolations(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude(".maplibregl-canvas")
    .analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.length}× — ${v.help}\n    ${v.nodes[0]?.target.join(" ")}`);
  expect(summary, `axe violations on ${context}`).toEqual([]);
}

/** Maps need WebGL. Some headless browsers (Firefox on CI runners) have none; e2e/resilience.spec.ts covers that case. */
export async function hasWebGL(page: Page): Promise<boolean> {
  return page.evaluate(() => !!document.createElement("canvas").getContext("webgl2") || !!document.createElement("canvas").getContext("webgl"));
}

/** A published listing id from the API (requires seed data). */
export async function anyListingId(request: APIRequestContext, query = "city=Pune"): Promise<string> {
  const response = await request.get(`/api/v1/search?${query}&limit=1`);
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { items: { id: string }[] };
  expect(body.items.length, "seed data needed: POST localhost:8002/internal/dev/seed").toBeGreaterThan(0);
  return body.items[0].id;
}
