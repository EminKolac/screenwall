// Groups for the findings panel: pending decisions, masked values by family, values left open.
import type { ItemKind, ReviewPayload, ReviewUnit } from "../../api/contract";
import { familyLabel } from "../../copy/tr";
import { slice } from "./text";

export interface PendingGroup {
  key: string;
  kind: ItemKind;
  family: string | null;
  text: string;
  reason: string;
  itemIds: string[];
  occurrences: number;
}

export interface MaskedEntry {
  key: string;
  family: string;
  surface: string;
  placeholder: string;
  reason: string;
  spanIds: string[];
  added: boolean;
  /** False in destructive mode: the original value was never stored, only the placeholder exists. */
  known: boolean;
}

export interface FamilyGroup {
  family: string;
  label: string;
  entries: MaskedEntry[];
  count: number;
}

export interface KeptEntry {
  key: string;
  surface: string;
  family: string | null;
  reason: string;
  spanIds: string[];
  itemIds: string[];
}

const FAMILY_ORDER = [
  "PERSON", "ORG", "TCKN", "VKN", "ID", "IBAN", "CREDIT_CARD", "PHONE", "EMAIL", "ADDRESS",
  "LOCATION", "DATE", "HEALTH", "SALARY", "PLATE", "URL", "IP", "SECRET", "CUSTOM",
];

const familyRank = (family: string) => {
  const at = FAMILY_ORDER.indexOf(family);
  return at < 0 ? FAMILY_ORDER.length : at;
};

export function buildGroups(payload: ReviewPayload, unitById: Map<string, ReviewUnit>) {
  const position = new Map(payload.units.map((u, i) => [u.id, i]));
  const reading = (a: { unit_id: string; start: number }, b: { unit_id: string; start: number }) =>
    (position.get(a.unit_id) ?? 0) - (position.get(b.unit_id) ?? 0) || a.start - b.start;

  const visibleText = (unitId: string, start: number, end: number, maskedStart: number, maskedEnd: number) => {
    const unit = unitById.get(unitId);
    if (!unit) return "";
    return unit.original !== null ? slice(unit.original, start, end) : slice(unit.masked, maskedStart, maskedEnd);
  };

  // Pending: one card per distinct text, so a repeated name needs one decision.
  const pendingMap = new Map<string, PendingGroup>();
  for (const item of [...payload.items].filter((i) => i.status === "open").sort(reading)) {
    const text = visibleText(item.unit_id, item.start, item.end, item.masked_start, item.masked_end);
    const key = `${item.kind}|${item.family ?? ""}|${text}`;
    const group = pendingMap.get(key);
    if (group) {
      group.itemIds.push(item.id);
      group.occurrences = Math.max(group.occurrences, item.occurrences, group.itemIds.length);
    } else {
      pendingMap.set(key, {
        key,
        kind: item.kind,
        family: item.family,
        text,
        reason: item.reason,
        itemIds: [item.id],
        occurrences: Math.max(1, item.occurrences),
      });
    }
  }

  // Masked: grouped by family, then by the value they hide.
  const families = new Map<string, Map<string, MaskedEntry>>();
  for (const span of [...payload.spans].filter((s) => s.state !== "kept").sort(reading)) {
    const unit = unitById.get(span.unit_id);
    if (!unit) continue;
    const surface = unit.original !== null ? slice(unit.original, span.start, span.end) : span.placeholder;
    const entries = families.get(span.family) ?? new Map<string, MaskedEntry>();
    families.set(span.family, entries);
    const entry = entries.get(surface);
    if (entry) {
      entry.spanIds.push(span.id);
      entry.added ||= span.state === "added";
    } else {
      entries.set(surface, {
        key: `${span.family}|${surface}`,
        family: span.family,
        surface,
        placeholder: span.placeholder,
        reason: span.reason,
        spanIds: [span.id],
        added: span.state === "added",
        known: unit.original !== null,
      });
    }
  }
  const masked: FamilyGroup[] = [...families.entries()]
    .map(([family, entries]) => ({
      family,
      label: familyLabel(family),
      entries: [...entries.values()],
      count: [...entries.values()].reduce((n, e) => n + e.spanIds.length, 0),
    }))
    .sort((a, b) => familyRank(a.family) - familyRank(b.family) || a.label.localeCompare(b.label, "tr"));

  // Left open: masks the person removed and suggestions they declined.
  const keptMap = new Map<string, KeptEntry>();
  const keep = (surface: string, family: string | null, reason: string, spanId?: string, itemId?: string) => {
    const entry = keptMap.get(surface) ?? { key: `kept|${surface}`, surface, family, reason, spanIds: [], itemIds: [] };
    if (spanId) entry.spanIds.push(spanId);
    if (itemId) entry.itemIds.push(itemId);
    keptMap.set(surface, entry);
  };
  for (const span of [...payload.spans].filter((s) => s.state === "kept").sort(reading)) {
    keep(visibleText(span.unit_id, span.start, span.end, span.masked_start, span.masked_end), span.family, span.reason, span.id);
  }
  for (const item of [...payload.items].filter((i) => i.status === "kept").sort(reading)) {
    keep(visibleText(item.unit_id, item.start, item.end, item.masked_start, item.masked_end), item.family, item.reason, undefined, item.id);
  }

  return { pending: [...pendingMap.values()], masked, kept: [...keptMap.values()] };
}
