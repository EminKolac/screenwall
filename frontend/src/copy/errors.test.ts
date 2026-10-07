import { describe, expect, it } from "vitest";
import type { ErrorCode } from "../api/contract";
import contractSource from "../api/contract.ts?raw";
import { clientErrorText, errorMessage, errorText, providerProblemText } from "./tr";

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
    const all = [...Object.values(errorText), ...Object.values(clientErrorText), ...Object.values(providerProblemText)];
    for (const sentence of all) {
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

  it("explains the Windows provider status in its own sentence", () => {
    // ProviderStatus.problem on Windows for claude_cli / codex_cli (backend chat/providers.py).
    expect(errorMessage("unsupported_os")).toBe(providerProblemText.unsupported_os);
    expect(errorMessage("unsupported_os")).toContain("Windows");
    // A status reason, not a request error: the contract's ErrorCode list stays as it is.
    expect(Object.keys(errorText)).not.toContain("unsupported_os");
  });
});
