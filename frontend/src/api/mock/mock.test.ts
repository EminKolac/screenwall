import { describe, expect, it } from "vitest";
import type { ReviewPayload } from "../contract";
import { applyDecision } from "./decisions";
import { createFixtures } from "./fixtures";
import { mockFetch } from "./router";
import { getDoc, putDoc, session, toPayload, toSummary } from "./store";
import { createUploadedDoc } from "./templates";
import type { MockDoc } from "./types";

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

let copies = 0;

/** A private copy of a fixture in the mock store, so router tests never share state. */
function stored(fixtureId: string): MockDoc {
  const doc: MockDoc = { ...createFixtures().find((d) => d.id === fixtureId)!, id: `${fixtureId}-copy${++copies}` };
  putDoc(doc);
  return doc;
}

const call = (method: string, path: string, json?: unknown) =>
  mockFetch(path, {
    method,
    headers: { "X-CSRF-Token": session.csrf, "Content-Type": "application/json" },
    body: json === undefined ? undefined : JSON.stringify(json),
  });

describe("mock backend revisions", () => {
  it("serves anonymized fixtures at revision 1 and bumps the revision on every decision", () => {
    const [deck] = createFixtures();
    expect(toSummary(deck).revision).toBe(1);
    const result = applyDecision(deck, { op: "unmask", target: { span_id: deck.spans[0].id }, scope: "occurrence" }, { always_mask: [], never_mask: [] });
    expect(result.ok).toBe(true);
    if (result.ok) expect(toPayload(result.doc).document.revision).toBe(2);
  });

  it("counts an upload as revision 0 until processing has anonymized it", () => {
    const now = Date.now();
    const later = now + 60_000;
    const upload = createUploadedDoc("Not.docx", "docx", "mapping", now);
    const broken = createUploadedDoc("bozuk.docx", "docx", "mapping", now);
    putDoc(upload);
    putDoc(broken);
    expect(toSummary(upload, now).revision).toBe(0);
    expect(toSummary(getDoc(upload.id, later)!, later)).toMatchObject({ status: "needs_review", revision: 1 });
    expect(toSummary(getDoc(broken.id, later)!, later)).toMatchObject({ status: "failed", revision: 0 });
  });

  it("answers 409 stale_revision to a decision or an approval made on another revision", async () => {
    const deck = stored("doc-sunum");
    const report = stored("doc-hasta");
    const decision = await call("POST", `/api/documents/${deck.id}/decisions`, {
      op: "unmask",
      target: { span_id: deck.spans[0].id },
      scope: "occurrence",
      expected_revision: deck.revision - 1,
    });
    const approval = await call("POST", `/api/documents/${report.id}/approve`, { expected_revision: report.revision + 1 });

    for (const res of [decision, approval]) {
      expect(res.status).toBe(409);
      expect(await res.json()).toEqual({ detail: "stale_revision" });
    }
    expect(getDoc(deck.id)).toMatchObject({ revision: deck.revision, spans: deck.spans });
    expect(toSummary(getDoc(report.id)!).status).toBe("needs_review");
  });

  it("applies a decision made on the current revision, then refuses the same one replayed on the old revision", async () => {
    const deck = stored("doc-sunum");
    const decision = { op: "unmask", target: { span_id: deck.spans[0].id }, scope: "occurrence", expected_revision: deck.revision };

    const first = await call("POST", `/api/documents/${deck.id}/decisions`, decision);
    expect(first.status).toBe(200);
    expect(((await first.json()) as ReviewPayload).document.revision).toBe(deck.revision + 1);

    const replay = await call("POST", `/api/documents/${deck.id}/decisions`, decision);
    expect(replay.status).toBe(409);
    expect(await replay.json()).toEqual({ detail: "stale_revision" });
  });

  it("approves when the body carries the current revision", async () => {
    const report = stored("doc-hasta");
    const res = await call("POST", `/api/documents/${report.id}/approve`, { expected_revision: report.revision });
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ status: "approved", revision: report.revision });
  });

  // Uploads process for 4 s: queued < 0.48 s ≤ extracting < 1.6 s ≤ masking < 2.8 s ≤ auditing < 4 s.
  it.each([
    ["extracting", 1_000],
    ["masking", 2_200],
    ["auditing", 3_400],
  ] as const)("refuses to delete a document while %s, and deletes it once processing is over", async (phase, elapsed) => {
    const upload = createUploadedDoc("Tutanak.docx", "docx", "mapping", Date.now() - elapsed);
    putDoc(upload);
    expect(toSummary(upload).status).toBe(phase);

    const busy = await call("DELETE", `/api/documents/${upload.id}`);
    expect(busy.status).toBe(409);
    expect(await busy.json()).toEqual({ detail: "document_busy" });
    expect(getDoc(upload.id)).toBeDefined();

    getDoc(upload.id, Date.now() + 60_000); // simulated processing time runs out
    const settled = await call("DELETE", `/api/documents/${upload.id}`);
    expect(settled.status).toBe(204);
    expect(getDoc(upload.id)).toBeUndefined();
  });

  it("deletes a document that is still waiting in the queue, like the backend (its job is skipped)", async () => {
    const queued = createUploadedDoc("Sırada.docx", "docx", "mapping", Date.now() + 60_000); // its turn has not come
    putDoc(queued);
    expect(toSummary(queued).status).toBe("queued");

    const res = await call("DELETE", `/api/documents/${queued.id}`);
    expect(res.status).toBe(204);
    expect(getDoc(queued.id)).toBeUndefined();
  });
});
