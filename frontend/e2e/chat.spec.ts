import { expect, test } from "@playwright/test";
import { mockRequests, openReady, sidePanel } from "./helpers";

test.beforeEach(async ({ page }) => {
  await openReady(page, "/d/doc-kira/sohbet", "Kira Sözleşmesi.docx");
});

test("local Ollama answers directly, with citations", async ({ page }) => {
  const panel = sidePanel(page);
  await expect(panel.getByRole("radio", { name: /Lokal LLM \(Ollama\)/ })).toBeChecked();
  await panel.getByLabel("Soru").fill("Kira bedeli ne kadar?");
  await panel.getByRole("button", { name: "Gönder", exact: true }).click();

  await expect(panel.getByRole("button", { name: /^Kaynak S1: Kira Sözleşmesi\.docx/ })).toBeVisible();
  const requests = await mockRequests(page);
  expect(requests).toContain("POST /api/chat");
  expect(requests).not.toContain("POST /api/chat/preview");
});

test("Claude needs the consent dialog, and sends only after the checkbox", async ({ page }) => {
  const panel = sidePanel(page);
  await panel.getByRole("radio", { name: /Claude/ }).check();
  await panel.getByLabel("Soru").fill("Depozito kime teslim edildi?");
  await panel.getByRole("button", { name: "Gönder", exact: true }).click();

  const dialog = page.getByRole("dialog", { name: "Gönderimi onaylayın" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Anthropic (Claude)").first()).toBeVisible();
  await expect(dialog.getByRole("region", { name: "Gönderilecek metin" })).toContainText("Soru: Depozito kime teslim edildi?");
  const send = dialog.getByRole("button", { name: "Gönder" });
  await expect(send).toBeDisabled();
  expect(await mockRequests(page)).not.toContain("POST /api/chat");

  await dialog.getByRole("checkbox", { name: "Bu metnin Anthropic (Claude) tarafına gönderileceğini anladım" }).check();
  await expect(send).toBeEnabled();
  await send.click();

  await expect(panel.getByRole("button", { name: /^Kaynak S1:/ })).toBeVisible();
  const requests = await mockRequests(page);
  expect(requests.filter((r) => r === "POST /api/chat/preview")).toHaveLength(1);
  expect(requests.filter((r) => r === "POST /api/chat")).toHaveLength(1);
});
