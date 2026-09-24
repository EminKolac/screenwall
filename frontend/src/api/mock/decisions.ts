// POST /decisions semantics for the mock: mask, unmask and keep at three scopes.
import type { DecisionRequest, DecisionScope, ErrorCode } from "../contract";
import { assignPlaceholder } from "./build";
import { cps, occurrences } from "./render";
import { surfaceOf } from "./store";
import type { MockDoc, MockItem, MockLists, MockSpan } from "./types";

export type DecisionResult = { ok: true; doc: MockDoc; lists: MockLists } | { ok: false; error: ErrorCode };

const fail = (error: ErrorCode): DecisionResult => ({ ok: false, error });
const USER_MASK = "Sizin kararınız: maskelendi";

interface Range {
  unit_id: string;
  start: number;
  end: number;
}

const overlaps = (a: Range, b: Range) => a.unit_id === b.unit_id && a.start < b.end && b.start < a.end;
const masking = (s: MockSpan) => s.state !== "kept";

function addTerm(list: string[], term: string): string[] {
  const fold = term.toLocaleLowerCase("tr");
  return list.some((t) => t.toLocaleLowerCase("tr") === fold) ? list : [...list, term];
}

function withList(lists: MockLists, scope: DecisionScope, key: keyof MockLists, term: string): MockLists {
  return scope === "global" ? { ...lists, [key]: addTerm(lists[key], term) } : lists;
}

/** Adds a user mask over `range`, replacing any kept span there and resolving covered items. */
function maskRange(doc: MockDoc, range: Range, family: string): MockDoc {
  if (doc.spans.some((s) => masking(s) && overlaps(s, range))) return doc;
  const surface = surfaceOf(doc, range.unit_id, range.start, range.end);
  const [placeholder, placeholders] = assignPlaceholder(doc.placeholders, family, surface);
  const seq = doc.seq + 1;
  const span: MockSpan = {
    id: `${doc.id}-s${seq}`,
    ...range,
    family,
    placeholder,
    evidence: ["user:mask"],
    reason: USER_MASK,
    state: "added",
  };
  return {
    ...doc,
    seq,
    placeholders,
    spans: [...doc.spans.filter((s) => !(s.state === "kept" && overlaps(s, range))), span],
    items: doc.items.map((i) => (i.status !== "masked" && overlaps(i, range) ? { ...i, status: "masked" as const } : i)),
  };
}

function decideSpan(doc: MockDoc, spanId: string, op: DecisionRequest["op"], scope: DecisionScope, lists: MockLists): DecisionResult {
  const span = doc.spans.find((s) => s.id === spanId);
  if (!span || op === "keep") return fail("invalid_decision");
  const surface = surfaceOf(doc, span.unit_id, span.start, span.end);
  const hit = (s: MockSpan) => (scope === "occurrence" ? s.id === span.id : surfaceOf(doc, s.unit_id, s.start, s.end) === surface);

  if (op === "unmask") {
    if (doc.mode === "destructive") return fail("original_not_stored");
    if (!masking(span)) return fail("invalid_decision");
    const removed = doc.spans.filter((s) => hit(s) && s.state === "added");
    const spans = doc.spans.flatMap((s) => (!hit(s) || !masking(s) ? [s] : s.state === "added" ? [] : [{ ...s, state: "kept" as const }]));
    const items = doc.items.map((i) => (i.status === "masked" && removed.some((s) => overlaps(s, i)) ? { ...i, status: "kept" as const } : i));
    return { ok: true, doc: { ...doc, spans, items }, lists: withList(lists, scope, "never_mask", surface) };
  }
  if (masking(span)) return fail("invalid_decision");
  const spans = doc.spans.map((s) => (hit(s) && s.state === "kept" ? { ...s, state: "masked" as const } : s));
  return { ok: true, doc: { ...doc, spans }, lists: withList(lists, scope, "always_mask", surface) };
}

function decideItem(doc: MockDoc, itemId: string, op: DecisionRequest["op"], scope: DecisionScope, lists: MockLists): DecisionResult {
  const item = doc.items.find((i) => i.id === itemId);
  if (!item || item.status === "masked" || op === "unmask") return fail("invalid_decision");
  const surface = surfaceOf(doc, item.unit_id, item.start, item.end);
  const targets: MockItem[] =
    scope === "occurrence"
      ? [item]
      : doc.items.filter((i) => i.status !== "masked" && surfaceOf(doc, i.unit_id, i.start, i.end) === surface);

  if (op === "keep") {
    const ids = new Set(targets.map((t) => t.id));
    const items = doc.items.map((i) => (ids.has(i.id) ? { ...i, status: "kept" as const } : i));
    return { ok: true, doc: { ...doc, items }, lists: withList(lists, scope, "never_mask", surface) };
  }
  const next = targets.reduce((acc, t) => maskRange(acc, t, t.family ?? "CUSTOM"), doc);
  const ids = new Set(targets.map((t) => t.id));
  const items = next.items.map((i) => (ids.has(i.id) ? { ...i, status: "masked" as const } : i));
  return { ok: true, doc: { ...next, items }, lists: withList(lists, scope, "always_mask", surface) };
}

function decideSelection(doc: MockDoc, target: Range & { family: string }, scope: DecisionScope, lists: MockLists): DecisionResult {
  const unit = doc.units.find((u) => u.id === target.unit_id);
  if (!unit) return fail("invalid_decision");
  if (doc.mode === "destructive") return fail("original_not_stored");
  const { start, end } = target;
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start < end && end <= cps(unit.original).length;
  if (!valid || doc.spans.some((s) => masking(s) && overlaps(s, target))) return fail("invalid_decision");
  const surface = surfaceOf(doc, unit.id, start, end);
  const found: Range[] =
    scope === "occurrence"
      ? []
      : doc.units.flatMap((u) => occurrences(u.original, surface).map(([a, b]) => ({ unit_id: u.id, start: a, end: b })));
  const ranges = [{ unit_id: unit.id, start, end }, ...found.filter((r) => !overlaps(r, target))];
  const next = ranges.reduce((acc, r) => maskRange(acc, r, target.family), doc);
  return { ok: true, doc: next, lists: withList(lists, scope, "always_mask", surface) };
}

export function applyDecision(doc: MockDoc, request: DecisionRequest, lists: MockLists): DecisionResult {
  const t = request.target;
  const result =
    "span_id" in t
      ? decideSpan(doc, t.span_id, request.op, request.scope, lists)
      : "item_id" in t
        ? decideItem(doc, t.item_id, request.op, request.scope, lists)
        : request.op === "mask"
          ? decideSelection(doc, t, request.scope, lists)
          : fail("invalid_decision");
  return result.ok ? { ...result, doc: { ...result.doc, updatedAt: Date.now() } } : result;
}
