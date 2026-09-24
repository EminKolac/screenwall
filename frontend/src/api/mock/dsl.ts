// Fixture markup: "İletişim: [[m:PERSON:Selin Özdemir|Alan etiketi]]" → plain text + code-point offsets.
// Kinds: m masked · a added · k kept · s suggestion · f finding. "ORG#kuzey" shares a placeholder key.

export interface DslMark {
  type: "m" | "a" | "k" | "s" | "f";
  family: string;
  entity: string | null;
  start: number;
  end: number;
  text: string;
  reason: string;
}

const TOKEN = /\[\[([makfs]):([A-Z_]+)(?:#([\w-]+))?:([^|\]]+)\|([^\]]+)\]\]/gu;

export function parseMarked(source: string): { text: string; marks: DslMark[] } {
  const marks: DslMark[] = [];
  let text = "";
  let length = 0;
  let last = 0;
  for (const match of source.matchAll(TOKEN)) {
    const [whole, type, family, entity, value, reason] = match;
    const before = source.slice(last, match.index);
    text += before;
    length += Array.from(before).length;
    const size = Array.from(value).length;
    marks.push({
      type: type as DslMark["type"],
      family,
      entity: entity ?? null,
      start: length,
      end: length + size,
      text: value,
      reason,
    });
    text += value;
    length += size;
    last = (match.index ?? 0) + whole.length;
  }
  text += source.slice(last);
  return { text, marks };
}
