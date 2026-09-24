// Turns compact fixture definitions into mock documents with consistent ids and placeholders.
import type { DocStatus, FileKind, Mode, ReviewReason, UnitKind } from "../contract";
import { parseMarked, type DslMark } from "./dsl";
import type { MockDoc, MockItem, MockPage, MockSpan, MockUnit, PageStyle, Processing } from "./types";

export interface UnitDef {
  text: string;
  location: string;
  kind?: UnitKind;
  page?: number;
  table?: { id: string; row: number; col: number };
}

export interface DocDef {
  id: string;
  filename: string;
  kind: FileKind;
  mode: Mode;
  status: DocStatus;
  createdAt: number;
  units: UnitDef[];
  pages?: { count: number; style: PageStyle; unreadable?: number[] };
  reasons?: ReviewReason[];
  processing?: Processing | null;
}

export const PAGE_SIZE: Record<PageStyle, { width: number; height: number }> = {
  slide: { width: 960, height: 540 },
  a4: { width: 595, height: 842 },
};

/** Same family + same value → same placeholder; new values get the next number. */
export function assignPlaceholder(
  placeholders: Record<string, string>,
  family: string,
  key: string,
): [string, Record<string, string>] {
  const id = `${family}|${key}`;
  const existing = placeholders[id];
  if (existing) return [existing, placeholders];
  const used = Object.keys(placeholders).filter((k) => k.startsWith(`${family}|`)).length;
  const placeholder = `<${family}_${used + 1}>`;
  return [placeholder, { ...placeholders, [id]: placeholder }];
}

const evidenceFor = (mark: DslMark): string[] => {
  if (/yayıldı/u.test(mark.reason)) return ["propagation:legal_suffix"];
  if (/etiket|alan/iu.test(mark.reason)) return [`context:label`, `recognizer:${mark.family}`];
  return [`recognizer:${mark.family}`];
};

export function buildDoc(def: DocDef): MockDoc {
  let placeholders: Record<string, string> = {};
  const units: MockUnit[] = [];
  const spans: MockSpan[] = [];
  const items: MockItem[] = [];
  let seq = 0;

  def.units.forEach((unit, index) => {
    const { text, marks } = parseMarked(unit.text);
    const id = unit.table ? `${unit.table.id}:r${unit.table.row}c${unit.table.col}` : `u${index + 1}`;
    units.push({
      id,
      block_id: unit.table ? unit.table.id : `b${index + 1}`,
      kind: unit.kind ?? (unit.table ? "cell" : "paragraph"),
      page: unit.page ?? null,
      location: unit.location,
      table: unit.table ?? null,
      original: text,
    });
    for (const mark of marks) {
      seq += 1;
      if (mark.type === "s" || mark.type === "f") {
        items.push({
          id: `${def.id}-i${seq}`,
          kind: mark.type === "s" ? "suggestion" : "finding",
          unit_id: id,
          start: mark.start,
          end: mark.end,
          family: mark.family,
          reason: mark.reason,
          status: "open",
        });
        continue;
      }
      const [placeholder, next] = assignPlaceholder(placeholders, mark.family, mark.entity ?? mark.text);
      placeholders = next;
      spans.push({
        id: `${def.id}-s${seq}`,
        unit_id: id,
        start: mark.start,
        end: mark.end,
        family: mark.family,
        placeholder,
        evidence: evidenceFor(mark),
        reason: mark.reason,
        state: mark.type === "m" ? "masked" : mark.type === "a" ? "added" : "kept",
      });
    }
  });

  const pages: MockPage[] = def.pages
    ? Array.from({ length: def.pages.count }, (_, i) => ({
        index: i + 1,
        ...PAGE_SIZE[def.pages!.style],
        style: def.pages!.style,
        unreadable: def.pages!.unreadable?.includes(i + 1) ?? false,
      }))
    : [];

  return {
    id: def.id,
    filename: def.filename,
    kind: def.kind,
    mode: def.mode,
    language: "tr",
    createdAt: def.createdAt,
    updatedAt: def.createdAt,
    status: def.status,
    // Fixtures arrive anonymized once; uploads get their first revision when processing finishes.
    revision: def.processing || def.status === "failed" ? 0 : 1,
    processing: def.processing ?? null,
    units,
    spans,
    items,
    pages,
    reasons: def.reasons ?? [],
    placeholders,
    seq,
  };
}
