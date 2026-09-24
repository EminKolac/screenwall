import { expect, test } from "@playwright/test";
import { fixturePdf, sidePanel } from "./helpers";

test("upload, review, unmask, decide, approve and download", async ({ page }) => {
  await page.goto("/");
  await page.locator('input[type="file"]').setInputFiles(fixturePdf());

  // The new document opens while it is processed, then turns into the review screen by itself.
  await expect(page.getByRole("heading", { level: 1, name: "Toplantı Notu.pdf" })).toBeVisible();
  const approve = page.getByRole("button", { name: "Onayla", exact: true });
  await expect(approve).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("2 karar bekliyor").first()).toBeVisible();

  const panel = sidePanel(page);

  // Unmask a value the engine masked.
  await panel.getByRole("button", { name: /^Deniz Aydın/ }).click();
  await panel.getByRole("button", { name: "Maskeyi kaldır" }).click();
  await expect(page.getByText("Kaydedildi").first()).toBeVisible();
  await expect(panel.getByText("Açık bırakılanlar")).toBeVisible();
  await expect(page.locator('[data-pane="original"] mark[data-state="kept"]').first()).toHaveText("Deniz Aydın");

  // Decide both suggestions.
  await panel.locator("[data-pending-card]").filter({ hasText: "Atlas Grubu" }).getByRole("button", { name: "Maskele" }).click();
  await expect(panel.locator("[data-pending-card]").filter({ hasText: "Atlas Grubu" })).toHaveCount(0);
  await panel.locator("[data-pending-card]").filter({ hasText: "Mavi Ofis" }).getByRole("button", { name: "Açık bırak" }).click();
  await expect(panel.locator("[data-pending-card]")).toHaveCount(0);
  await expect(page.getByText("Onaya hazır").first()).toBeVisible();

  // Approve through the confirmation dialog.
  await approve.click();
  const dialog = page.getByRole("dialog", { name: "Belgeyi onayla" });
  await dialog.getByRole("button", { name: "Onayla" }).click();
  await expect(dialog).toBeHidden();

  const download = page.getByRole("button", { name: "İndir" });
  await expect(download).toBeVisible();
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  expect(file.suggestedFilename()).toBe("Toplantı Notu-maskeli.pdf");
});
