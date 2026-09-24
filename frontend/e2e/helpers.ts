import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

export const fixturePdf = () => ({
  name: "Toplantı Notu.pdf",
  mimeType: "application/pdf",
  buffer: readFileSync(fileURLToPath(new URL("./fixtures/toplanti-notu.pdf", import.meta.url))),
});

/** Requests the in-browser mock has served so far ("METHOD /path"). */
export async function mockRequests(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const log = (window as unknown as { __screenwallMock?: { requests: Array<{ method: string; path: string }> } }).__screenwallMock;
    return (log?.requests ?? []).map((r) => `${r.method} ${r.path}`);
  });
}

export const sidePanel = (page: Page) => page.getByRole("region", { name: "Bulgular ve sohbet" });

export async function openReady(page: Page, path: string, heading: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}
