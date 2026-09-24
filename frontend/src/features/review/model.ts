// Pure derivation of everything the review screen draws from one ReviewPayload.
import type { ItemKind, ReviewItem, ReviewPayload, ReviewSpan, ReviewUnit } from "../../api/contract";
import { tr } from "../../copy/tr";
import { buildGroups, type FamilyGroup, type KeptEntry, type PendingGroup } from "./groups";

export type MarkState = "masked" | "added" | "kept" | "suggestion" | "finding";

/** A highlighted range inside one text, in code points. */
export interface TextMark {
  id: string;
  start: number;
  end: number;
  state: MarkState;
  family: string | null;
  reason: string;
}

export interface MarkRef {
  id: string;
  unitId: string;
  kind: "span" | "item";
  start: number;
  state: MarkState;
  family: string | null;
  reason: string;
}

export interface UnitBlock {
  kind: "unit";
  key: string;
  unit: ReviewUnit;
}

export interface TableBlock {
  kind: "table";
  key: string;
  index: number;
  rows: Array<Array<ReviewUnit | null>>;
}

export type Block = UnitBlock | TableBlock;

export interface Section {
  key: string;
  label: string;
  page: number | null;
  blocks: Block[];
  /** A PDF page the extractor could not read: it has no units. */
  empty: boolean;
}

export interface ReviewModel {
  units: ReviewUnit[];
  unitById: Map<string, ReviewUnit>;
  originalMarks: Map<string, TextMark[]>;
  maskedMarks: Map<string, TextMark[]>;
  sections: Section[];
  marks: Map<string, MarkRef>;
  /** Every mark in reading order (J/K when nothing is pending). */
  order: string[];
  /** Open items in reading order (J/K while decisions are pending). */
  pendingOrder: string[];
  pending: PendingGroup[];
  masked: FamilyGroup[];
  kept: KeptEntry[];
}

function itemState(item: ReviewItem): MarkState | null {
  if (item.status === "open") return item.kind satisfies ItemKind;
  if (item.status === "kept") return "kept";
  return null; // masked items are represented by the span that replaced them
}

function push<T>(map: Map<string, T[]>, key: string, value: T) {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

function sectionOf(unit: ReviewUnit): { key: string; label: string; page: number | null } {
  if (unit.page !== null) return { key: `p${unit.page}`, label: tr.review.page.label(unit.page), page: unit.page };
  const head = unit.location.split(" · ")[0]?.trim() || unit.location;
  return { key: `l:${head}`, label: head, page: null };
}

function buildTable(cells: ReviewUnit[], key: string, index: number): TableBlock {
  const rowCount = Math.max(...cells.map((c) => (c.table?.row ?? 0) + 1));
  const colCount = Math.max(...cells.map((c) => (c.table?.col ?? 0) + 1));
  const rows: Array<Array<ReviewUnit | null>> = Array.from({ length: rowCount }, () => Array(colCount).fill(null));
  for (const cell of cells) if (cell.table) rows[cell.table.row][cell.table.col] = cell;
  return { kind: "table", key, index, rows };
}

function buildSections(payload: ReviewPayload): Section[] {
  const sections: Section[] = [];
  let tableIndex = 0;
  for (let i = 0; i < payload.units.length; i++) {
    const unit = payload.units[i];
    const where = sectionOf(unit);
    let section = sections[sections.length - 1];
    if (!section || section.key !== where.key) {
      section = { ...where, blocks: [], empty: false };
      sections.push(section);
    }
    if (unit.table) {
      const tableId = unit.table.id;
      const cells: ReviewUnit[] = [];
      while (i < payload.units.length && payload.units[i].table?.id === tableId) cells.push(payload.units[i++]);
      i -= 1;
      tableIndex += 1;
      section.blocks.push(buildTable(cells, `t:${tableId}:${cells[0].id}`, tableIndex));
    } else {
      section.blocks.push({ kind: "unit", key: unit.id, unit });
    }
  }
  // Pages the extractor could not read still get a place in the reading order.
  const withText = new Set(payload.units.map((u) => u.page).filter((p): p is number => p !== null));
  for (const page of payload.pages) {
    if (withText.has(page.index)) continue;
    const at = sections.findIndex((s) => s.page !== null && s.page > page.index);
    const empty: Section = { key: `p${page.index}`, label: tr.review.page.label(page.index), page: page.index, blocks: [], empty: true };
    if (at < 0) sections.push(empty);
    else sections.splice(at, 0, empty);
  }
  return sections;
}

export function buildModel(payload: ReviewPayload): ReviewModel {
  const unitById = new Map(payload.units.map((u) => [u.id, u]));
  const position = new Map(payload.units.map((u, i) => [u.id, i]));
  const originalMarks = new Map<string, TextMark[]>();
  const maskedMarks = new Map<string, TextMark[]>();
  const marks = new Map<string, MarkRef>();

  const addSpan = (span: ReviewSpan) => {
    const base = { id: span.id, state: span.state, family: span.family, reason: span.reason } as const;
    push(originalMarks, span.unit_id, { ...base, start: span.start, end: span.end });
    push(maskedMarks, span.unit_id, { ...base, start: span.masked_start, end: span.masked_end });
    marks.set(span.id, { ...base, unitId: span.unit_id, kind: "span", start: span.start });
  };
  payload.spans.filter((s) => unitById.has(s.unit_id)).forEach(addSpan);

  for (const item of payload.items) {
    const state = itemState(item);
    if (!state || !unitById.has(item.unit_id)) continue;
    const base = { id: item.id, state, family: item.family, reason: item.reason };
    push(originalMarks, item.unit_id, { ...base, start: item.start, end: item.end });
    push(maskedMarks, item.unit_id, { ...base, start: item.masked_start, end: item.masked_end });
    marks.set(item.id, { ...base, unitId: item.unit_id, kind: "item", start: item.start });
  }

  const byReading = (a: MarkRef, b: MarkRef) =>
    (position.get(a.unitId) ?? 0) - (position.get(b.unitId) ?? 0) || a.start - b.start;
  const ordered = [...marks.values()].sort(byReading);
  const groups = buildGroups(payload, unitById);

  return {
    units: payload.units,
    unitById,
    originalMarks,
    maskedMarks,
    sections: buildSections(payload),
    marks,
    order: ordered.map((m) => m.id),
    pendingOrder: ordered.filter((m) => m.state === "suggestion" || m.state === "finding").map((m) => m.id),
    ...groups,
  };
}
