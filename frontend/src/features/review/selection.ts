// Turning a DOM text selection in the original pane into contract offsets (code points).
import type { ReviewSpan } from "../../api/contract";
import { chars } from "./text";

export interface TextSelectionInfo {
  unitId: string;
  start: number;
  end: number;
  text: string;
  range: Range | null;
}

function unitElement(node: Node | null): HTMLElement | null {
  const element = node instanceof HTMLElement ? node : node?.parentElement ?? null;
  return element?.closest<HTMLElement>("[data-unit-text]") ?? null;
}

/** Code points between the start of `container` and (node, offset). */
export function codePointOffset(container: HTMLElement, node: Node, offset: number): number {
  const range = document.createRange();
  range.setStart(container, 0);
  range.setEnd(node, offset);
  return chars(range.toString()).length;
}

/**
 * The current selection, if it lies inside exactly one unit of the original pane. Leading and
 * trailing whitespace is trimmed so a double-clicked word never drags a space into the mask.
 */
export function readOriginalSelection(
  root: HTMLElement | null,
  unitText: (unitId: string) => string | null,
): TextSelectionInfo | null {
  const selection = window.getSelection();
  if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const unit = unitElement(range.startContainer);
  if (!unit || unit !== unitElement(range.endContainer) || !root.contains(unit)) return null;
  if (!unit.closest('[data-pane="original"]')) return null;
  const unitId = unit.dataset.unitText;
  const full = unitId ? unitText(unitId) : null;
  if (!unitId || full === null) return null;

  const cps = chars(full);
  let start = codePointOffset(unit, range.startContainer, range.startOffset);
  let end = Math.min(codePointOffset(unit, range.endContainer, range.endOffset), cps.length);
  while (start < end && /\s/u.test(cps[start])) start += 1;
  while (end > start && /\s/u.test(cps[end - 1])) end -= 1;
  if (start >= end) return null;
  return { unitId, start, end, text: cps.slice(start, end).join(""), range: range.cloneRange() };
}

/** True when the range touches a value that is already masked. */
export function overlapsMasked(spans: ReviewSpan[], unitId: string, start: number, end: number): boolean {
  return spans.some((s) => s.unit_id === unitId && s.state !== "kept" && s.start < end && s.end > start);
}

/** A sensible default family for a hand-made selection. */
export function guessFamily(text: string): string {
  const value = text.trim();
  if (/@/.test(value)) return "EMAIL";
  if (/^TR\s?\d{2}/i.test(value)) return "IBAN";
  if (/^\d{11}$/.test(value)) return "TCKN";
  if (/^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$/.test(value)) return "DATE";
  if ((value.match(/\d/g) ?? []).length >= 7) return "PHONE";
  if (/(A\.Ş\.|Ltd|Holding|Grubu|Şirketi|Vakfı|Derneği)/u.test(value)) return "ORG";
  if (/(Cad\.|Sok\.|Mah\.|Bulvarı|No:)/u.test(value)) return "ADDRESS";
  return "PERSON";
}
