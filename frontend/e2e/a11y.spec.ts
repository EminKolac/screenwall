import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const views = [
  { name: "library", path: "/", ready: "Bir belge seçin" },
  { name: "review", path: "/d/doc-sunum", ready: "Yatırımcı Sunumu 2026-Ç2.pdf" },
];

for (const scheme of ["light", "dark"] as const) {
  for (const view of views) {
    test(`${view.name} has no axe violations (${scheme})`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.goto(view.path);
      const ready = testInfo.project.name === "mobile" && view.name === "library" ? "Belgeler" : view.ready;
      await expect(page.getByRole("heading", { level: 1, name: ready })).toBeVisible();
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
      const results = await new AxeBuilder({ page }).analyze();
      const summary = results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
      expect(summary).toEqual([]);
    });
  }
}
