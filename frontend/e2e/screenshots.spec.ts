import { expect, test } from "@playwright/test";
import { openReady, sidePanel } from "./helpers";

const out = (name: string) => `e2e/__screenshots__/${name}.png`;

test.describe("screenshots", () => {
  test("library, review, consent and dark review", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "Desktop 1440×900 only");
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await openReady(page, "/", "Bir belge seçin");
    await page.screenshot({ path: out("library-1440-light") });

    await openReady(page, "/d/doc-sunum", "Yatırımcı Sunumu 2026-Ç2.pdf");
    await expect(page.locator("[data-pending-card]").first()).toBeVisible();
    await page.screenshot({ path: out("review-1440-light") });

    await openReady(page, "/d/doc-kira/sohbet", "Kira Sözleşmesi.docx");
    const panel = sidePanel(page);
    await panel.getByRole("radio", { name: /Claude/ }).check();
    await panel.getByLabel("Soru").fill("Kira bedeli ne kadar ve nasıl ödeniyor?");
    await panel.getByRole("button", { name: "Gönder", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Gönderimi onaylayın" })).toBeVisible();
    await page.screenshot({ path: out("consent-1440-light") });

    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await openReady(page, "/d/doc-sunum", "Yatırımcı Sunumu 2026-Ç2.pdf");
    await expect(page.locator("[data-pending-card]").first()).toBeVisible();
    await page.screenshot({ path: out("review-1440-dark") });
  });
});
