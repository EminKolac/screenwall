import { describe, expect, it } from "vitest";
import type { ErrorCode } from "../api/contract";
import contractSource from "../api/contract.ts?raw";
import { clientErrorText, errorMessage, errorText } from "./tr";

// Compile time: the map must have exactly the contract's codes.
type Missing = Exclude<ErrorCode, keyof typeof errorText>;
type Extra = Exclude<keyof typeof errorText, ErrorCode>;
const exhaustive: [Missing, Extra] extends [never, never] ? true : false = true;

function contractCodes(): string[] {
  const block = /export type ErrorCode =([\s\S]*?);/.exec(contractSource)?.[1] ?? "";
  return [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("error dictionary", () => {
  it("covers every ErrorCode declared in contract.ts, and nothing else", () => {
    const codes = contractCodes();
    expect(exhaustive).toBe(true);
    expect(codes.length).toBeGreaterThan(20);
    expect(Object.keys(errorText).sort()).toEqual([...codes].sort());
  });

  it("uses calm Turkish sentences", () => {
    for (const sentence of [...Object.values(errorText), ...Object.values(clientErrorText)]) {
      expect(sentence).toMatch(/^[A-ZÇĞİÖŞÜ]/);
      expect(sentence).toMatch(/\.$/);
      expect(sentence).not.toMatch(/!/);
      expect(sentence.toLocaleLowerCase("tr")).not.toContain("başarıyla");
    }
  });

  it("falls back to a generic sentence for unknown codes", () => {
    expect(errorMessage("unresolved_items")).toBe(errorText.unresolved_items);
    expect(errorMessage("network_error")).toBe(clientErrorText.network_error);
    expect(errorMessage("something_new")).toBe(clientErrorText.unknown_error);
  });
});
