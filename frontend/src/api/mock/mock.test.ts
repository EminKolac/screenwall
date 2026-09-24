import { describe, expect, it } from "vitest";
import type { ReviewPayload } from "../contract";
import { applyDecision } from "./decisions";
import { createFixtures } from "./fixtures";
import { toPayload, toSummary } from "./store";

const cps = (s: string) => Array.from(s);
const slice = (s: string, a: number, b: number) => cps(s).slice(a, b).join("");

function assertConsistent(payload: ReviewPayload) {
  const units = new Map(payload.units.map((u) => [u.id, u]));
  for (const span of payload.spans) {
    const unit = units.get(span.unit_id)!;
    const shown = slice(unit.masked, span.masked_start, span.masked_end);
    if (span.state === "kept") expect(shown).toBe(slice(unit.original ?? shown, span.start, span.end));
    else expect(shown).toBe(span.placeholder);
  }
  for (const item of payload.items.filter((i) => i.status !== "masked")) {
    const unit = units.get(item.unit_id)!;
    if (unit.original !== null) {
      expect(slice(unit.masked, item.masked_start, item.masked_end)).toBe(slice(unit.original, item.start, item.end));
    }
  }
}

describe("mock backend", () => {
  it("serves self-consistent offsets for every fixture", () => {
    for (const doc of createFixtures()) assertConsistent(toPayload(doc));
  });

  it("follows the contract's review rules", () => {
    const [deck] = createFixtures();
    const summary = toSummary(deck);
    expect(summary.status).toBe("needs_review");
    expect(summary.counts.pending).toBe(4);
    expect(summary.can).toMatchObject({ review: true, approve: false, decide: true, chat: false });
  });

  it("keeps offsets consistent through unmask, keep and selection decisions", () => {
    const lists = { always_mask: [], never_mask: [] };
    let doc = createFixtures()[0];
    const kuzey = doc.items.find((i) => i.reason.includes("tek başına"))!;
    const steps = [
      { op: "unmask" as const, target: { span_id: doc.spans[0].id }, scope: "document" as const },
      { op: "keep" as const, target: { item_id: kuzey.id }, scope: "document" as const },
      { op: "mask" as const, target: { unit_id: "u5", start: 0, end: 7, family: "CUSTOM" }, scope: "occurrence" as const },
    ];
    for (const step of steps) {
      const result = applyDecision(doc, step, lists);
      expect(result.ok).toBe(true);
      if (result.ok) doc = result.doc;
      assertConsistent(toPayload(doc));
    }
    // Document scope follows the same text: "Kuzey Enerji Dağıtım A.Ş." shares the placeholder but stays masked.
    expect(doc.spans.filter((s) => s.state === "kept")).toHaveLength(1);
    expect(doc.spans.find((s) => s.id === doc.spans[0].id)?.state).toBe("kept");
    expect(doc.items.filter((i) => i.status === "kept")).toHaveLength(2);
    expect(toPayload(doc).units.find((u) => u.id === "u5")!.masked.startsWith("<CUSTOM_1>")).toBe(true);
  });

  it("refuses to unmask when the original was never stored", () => {
    const receipt = createFixtures().find((d) => d.mode === "destructive")!;
    const result = applyDecision({ ...receipt, status: "needs_review" }, { op: "unmask", target: { span_id: receipt.spans[0].id }, scope: "occurrence" }, { always_mask: [], never_mask: [] });
    expect(result).toEqual({ ok: false, error: "original_not_stored" });
  });
});
