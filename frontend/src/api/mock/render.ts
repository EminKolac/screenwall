// Derives the masked text of a unit from its original text and spans, like the real engine.
import type { MockSpan, MockUnit } from "./types";

export interface RenderedUnit {
  masked: string;
  /** span id → [masked_start, masked_end] */
  ranges: Map<string, [number, number]>;
  /** Maps an original offset outside masked spans to the masked text. */
  toMasked: (offset: number) => number;
}

export const cps = (text: string) => Array.from(text);

export function unitSpans(spans: MockSpan[], unitId: string): MockSpan[] {
  return spans.filter((s) => s.unit_id === unitId).sort((a, b) => a.start - b.start);
}

export function renderUnit(unit: MockUnit, spans: MockSpan[]): RenderedUnit {
  const chars = cps(unit.original);
  const ranges = new Map<string, [number, number]>();
  const shifts: Array<{ at: number; delta: number }> = [];
  let out = "";
  let pos = 0;
  let masked = 0;
  for (const span of unitSpans(spans, unit.id)) {
    if (span.start < pos) continue; // overlapping spans are rejected at creation; stay defensive
    out += chars.slice(pos, span.start).join("");
    masked += span.start - pos;
    const replacement = span.state === "kept" ? chars.slice(span.start, span.end).join("") : span.placeholder;
    const size = cps(replacement).length;
    ranges.set(span.id, [masked, masked + size]);
    shifts.push({ at: span.end, delta: size - (span.end - span.start) });
    out += replacement;
    masked += size;
    pos = span.end;
  }
  out += chars.slice(pos).join("");
  const toMasked = (offset: number) => offset + shifts.filter((s) => s.at <= offset).reduce((n, s) => n + s.delta, 0);
  return { masked: out, ranges, toMasked };
}

/** Non-overlapping, word-bounded occurrences of `needle` in `text` (code points). */
export function occurrences(text: string, needle: string): Array<[number, number]> {
  const hay = cps(text);
  const pin = cps(needle);
  const word = /[\p{L}\p{N}]/u;
  const found: Array<[number, number]> = [];
  if (!pin.length) return found;
  for (let i = 0; i + pin.length <= hay.length; i++) {
    let same = true;
    for (let j = 0; j < pin.length && same; j++) same = hay[i + j] === pin[j];
    if (!same) continue;
    const before = i > 0 ? hay[i - 1] : "";
    const after = hay[i + pin.length] ?? "";
    if ((before && word.test(before)) || (after && word.test(after))) continue;
    found.push([i, i + pin.length]);
    i += pin.length - 1;
  }
  return found;
}
