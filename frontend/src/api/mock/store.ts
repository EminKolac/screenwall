// The mock "database": documents, settings and the session token, plus contract-shaped views.
import type { AppSettings, DocStatus, DocumentSummary, ReviewItem, ReviewPayload, ReviewSpan } from "../contract";
import { createFixtures } from "./fixtures";
import { cps, renderUnit } from "./render";
import type { MockDoc } from "./types";

let docs: MockDoc[] = createFixtures();
let settings: AppSettings = { default_mode: "mapping", chat_default_provider: "ollama", always_mask: [], never_mask: [] };
const csrf = `mock-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;

export const session = { csrf };

export function getSettings(): AppSettings {
  return settings;
}

export function saveSettings(next: AppSettings): AppSettings {
  settings = { ...next, always_mask: [...next.always_mask], never_mask: [...next.never_mask] };
  return settings;
}

/** Finish processing whose simulated time is up. */
function settle(doc: MockDoc, now: number): MockDoc {
  if (!doc.processing || now < doc.processing.start + doc.processing.duration) return doc;
  const done: MockDoc = {
    ...doc,
    status: doc.processing.outcome,
    processing: null,
    updatedAt: doc.processing.start + doc.processing.duration,
  };
  putDoc(done);
  return done;
}

export function allDocs(now = Date.now()): MockDoc[] {
  return docs.map((d) => settle(d, now));
}

export function getDoc(id: string, now = Date.now()): MockDoc | undefined {
  const doc = docs.find((d) => d.id === id);
  return doc ? settle(doc, now) : undefined;
}

export function putDoc(doc: MockDoc): void {
  docs = docs.some((d) => d.id === doc.id) ? docs.map((d) => (d.id === doc.id ? doc : d)) : [doc, ...docs];
}

export function dropDoc(id: string): void {
  docs = docs.filter((d) => d.id !== id);
}

export function statusOf(doc: MockDoc, now = Date.now()): DocStatus {
  if (!doc.processing) return doc.status;
  const t = (now - doc.processing.start) / doc.processing.duration;
  if (t < 0.12) return "queued";
  if (t < 0.4) return "extracting";
  if (t < 0.7) return "masking";
  if (t < 1) return "auditing";
  return doc.processing.outcome;
}

const iso = (ms: number) => new Date(ms).toISOString();

export function toSummary(doc: MockDoc, now = Date.now()): DocumentSummary {
  const status = statusOf(doc, now);
  const reviewable = status === "needs_review" || status === "approved";
  const pending = reviewable ? doc.items.filter((i) => i.status === "open").length : 0;
  const pdfPages = doc.pages.length || Math.max(1, ...doc.units.map((u) => u.page ?? 1));
  return {
    id: doc.id,
    filename: doc.filename,
    kind: doc.kind,
    mode: doc.mode,
    language: doc.language,
    status,
    created_at: iso(doc.createdAt),
    updated_at: iso(doc.updatedAt),
    pages: doc.kind === "pdf" ? pdfPages : null,
    counts: { masked: reviewable ? doc.spans.filter((s) => s.state !== "kept").length : 0, pending },
    reasons: status === "needs_review" || status === "failed" || status === "rejected" ? doc.reasons : [],
    can: {
      review: reviewable,
      approve: status === "needs_review" && pending === 0,
      download: status === "approved",
      chat: status === "approved",
      decide: status === "needs_review",
    },
  };
}

export const surfaceOf = (doc: MockDoc, unitId: string, start: number, end: number): string =>
  cps(doc.units.find((u) => u.id === unitId)?.original ?? "").slice(start, end).join("");

export function toPayload(doc: MockDoc): ReviewPayload {
  const destructive = doc.mode === "destructive";
  const rendered = new Map(doc.units.map((u) => [u.id, renderUnit(u, doc.spans)]));
  const spans: ReviewSpan[] = doc.spans.map((s) => {
    const [maskedStart, maskedEnd] = rendered.get(s.unit_id)?.ranges.get(s.id) ?? [0, 0];
    return { ...s, masked_start: maskedStart, masked_end: maskedEnd, evidence: [...s.evidence] };
  });
  const items: ReviewItem[] = doc.items.map((item) => {
    const view = rendered.get(item.unit_id);
    const cover = doc.spans.find(
      (s) => s.unit_id === item.unit_id && s.state !== "kept" && s.start <= item.start && s.end >= item.end,
    );
    const range = item.status === "masked" && cover ? view?.ranges.get(cover.id) : undefined;
    const surface = surfaceOf(doc, item.unit_id, item.start, item.end);
    return {
      ...item,
      masked_start: range ? range[0] : view?.toMasked(item.start) ?? 0,
      masked_end: range ? range[1] : view?.toMasked(item.end) ?? 0,
      occurrences: Math.max(1, doc.items.filter((i) => surfaceOf(doc, i.unit_id, i.start, i.end) === surface).length),
    };
  });
  return {
    document: toSummary(doc),
    units: doc.units.map((u) => ({
      id: u.id,
      block_id: u.block_id,
      kind: u.kind,
      page: u.page,
      location: u.location,
      table: u.table,
      original: destructive ? null : u.original,
      masked: rendered.get(u.id)?.masked ?? "",
    })),
    spans,
    items,
    pages: destructive ? [] : doc.pages.map(({ index, width, height }) => ({ index, width, height })),
  };
}

export function maskedText(doc: MockDoc): string {
  return toPayload(doc).units.map((u) => u.masked).join("\n\n");
}
