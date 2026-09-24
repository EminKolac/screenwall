// Renders "scanned" original pages as SVG and computes normalised mark rectangles from the same
// layout, so the overlay lines up exactly. Every word is its own <text> with a forced textLength.
import type { PageMarks } from "../contract";
import { cps } from "./render";
import type { MockDoc, MockPage } from "./types";

interface Token {
  text: string;
  start: number;
  end: number;
  x: number;
  w: number;
}

interface Line {
  unitId: string;
  y: number;
  size: number;
  bold: boolean;
  tokens: Token[];
}

const STYLE = {
  slide: { margin: 72, top: 132, heading: 40, body: 25, lead: 1.45, gap: 20 },
  a4: { margin: 60, top: 104, heading: 17, body: 11.5, lead: 1.6, gap: 10 },
};

// Page artwork colours come from the --scan-* tokens: a picture of paper, the same in both themes.
// An <img> cannot read CSS variables, so the values are resolved when the SVG is generated.
function scan(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(`--scan-${name}`).trim() || fallback;
}

function charWidth(ch: string): number {
  if (/\s/u.test(ch)) return 0.26;
  if (/[il.,:;'|!ıìí·]/u.test(ch)) return 0.28;
  if (/[fjrt()\-/I]/u.test(ch)) return 0.36;
  if (/[mwMW]/u.test(ch)) return 0.82;
  if (/[@%&]/u.test(ch)) return 0.8;
  if (/[A-ZÇĞİÖŞÜ]/u.test(ch)) return 0.66;
  if (/\d/u.test(ch)) return 0.56;
  return 0.5;
}

const widthOf = (text: string, size: number) => cps(text).reduce((w, ch) => w + charWidth(ch), 0) * size;

function tokenize(text: string) {
  const chars = cps(text);
  const out: Array<{ text: string; start: number; end: number; space: boolean }> = [];
  let i = 0;
  while (i < chars.length) {
    const kind = /\s/u.test(chars[i]) ? "space" : /[\p{L}\p{N}]/u.test(chars[i]) ? "word" : "mark";
    let j = i + 1;
    if (kind !== "mark") while (j < chars.length && (kind === "space" ? /\s/u : /[\p{L}\p{N}]/u).test(chars[j])) j++;
    out.push({ text: chars.slice(i, j).join(""), start: i, end: j, space: kind === "space" });
    i = j;
  }
  return out;
}

export function layoutPage(doc: MockDoc, page: MockPage): Line[] {
  const style = STYLE[page.style];
  const right = page.width - style.margin;
  const lines: Line[] = [];
  let y = style.top;
  for (const unit of doc.units.filter((u) => u.page === page.index)) {
    const bold = unit.kind === "heading";
    const size = bold ? style.heading : style.body;
    let tokens: Token[] = [];
    let x = style.margin;
    const flush = () => {
      if (tokens.length) lines.push({ unitId: unit.id, y, size, bold, tokens });
      y += size * style.lead;
      tokens = [];
      x = style.margin;
    };
    for (const token of tokenize(unit.original)) {
      const w = widthOf(token.text, size) * (bold ? 1.05 : 1);
      if (token.space) {
        if (tokens.length) x += w;
        continue;
      }
      if (x + w > right && tokens.length) flush();
      tokens.push({ text: token.text, start: token.start, end: token.end, x, w });
      x += w;
    }
    flush();
    y += style.gap + (bold ? size * 0.4 : 0);
  }
  return lines;
}

const escape = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const r = (n: number) => Math.round(n * 100) / 100;

function decoration(page: MockPage): string {
  const RULE = scan("rule", "gainsboro");
  const FAINT = scan("faint", "gray");
  if (page.style === "slide") {
    return `<rect x="0" y="0" width="${page.width}" height="8" fill="${RULE}"/><line x1="72" y1="486" x2="${page.width - 72}" y2="486" stroke="${RULE}"/><text x="${page.width - 72}" y="512" font-size="13" fill="${FAINT}" text-anchor="end">${page.index}</text>`;
  }
  return `<line x1="60" y1="64" x2="${page.width - 60}" y2="64" stroke="${RULE}"/><text x="${page.width / 2}" y="${page.height - 36}" font-size="9" fill="${FAINT}" text-anchor="middle">${page.index}</text>`;
}

function unreadable(page: MockPage): string {
  const bars = Array.from({ length: 22 }, (_, i) => {
    const width = 180 + ((i * 97) % 260);
    return `<rect x="${60 + ((i * 37) % 40)}" y="${110 + i * 28}" width="${width}" height="9" rx="4" fill="${scan("noise", "darkgray")}" opacity="${0.35 + ((i * 13) % 5) / 12}"/>`;
  }).join("");
  return `<rect width="100%" height="100%" fill="${scan("grey", "whitesmoke")}"/><filter id="blur"><feGaussianBlur stdDeviation="4"/></filter><g filter="url(#blur)">${bars}</g><path d="M0 ${page.height * 0.62} L${page.width} ${page.height * 0.48}" stroke="${scan("smudge", "silver")}" stroke-width="30" opacity=".5"/>`;
}

export function pageSvg(doc: MockDoc, page: MockPage): string {
  const body = page.unreadable
    ? unreadable(page)
    : layoutPage(doc, page)
        .map((line) =>
          line.tokens
            .map(
              (t) =>
                `<text x="${r(t.x)}" y="${r(line.y)}" font-size="${line.size}"${line.bold ? ' font-weight="700"' : ""} textLength="${r(t.w)}" lengthAdjust="spacingAndGlyphs">${escape(t.text)}</text>`,
            )
            .join(""),
        )
        .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${page.width}" height="${page.height}" viewBox="0 0 ${page.width} ${page.height}"><rect width="100%" height="100%" fill="${scan("bg", "white")}"/>${page.unreadable ? "" : decoration(page)}<g font-family="Georgia, 'Times New Roman', serif" fill="${scan("ink", "black")}">${body}</g></svg>`;
}

export const svgDataUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

export function pageMarks(doc: MockDoc, page: MockPage): PageMarks {
  const lines = page.unreadable ? [] : layoutPage(doc, page);
  const pad = 2;
  const rectsFor = (unitId: string, start: number, end: number): [number, number, number, number][] =>
    lines
      .filter((line) => line.unitId === unitId)
      .flatMap((line) => {
        const hit = line.tokens.filter((t) => t.start < end && t.end > start);
        if (!hit.length) return [];
        const first = hit[0];
        const last = hit[hit.length - 1];
        const x0 = first.x + (start > first.start ? (first.w * (start - first.start)) / (first.end - first.start) : 0);
        const x1 = last.x + (end < last.end ? (last.w * (end - last.start)) / (last.end - last.start) : last.w);
        return [
          [
            r((x0 - pad) / page.width * 1e4) / 1e4,
            r((line.y - line.size * 0.84) / page.height * 1e4) / 1e4,
            r((x1 + pad) / page.width * 1e4) / 1e4,
            r((line.y + line.size * 0.28) / page.height * 1e4) / 1e4,
          ] as [number, number, number, number],
        ];
      });

  const onPage = new Set(doc.units.filter((u) => u.page === page.index).map((u) => u.id));
  const marks: PageMarks["marks"] = [
    ...doc.spans
      .filter((s) => onPage.has(s.unit_id))
      .map((s) => ({ ref: s.id, kind: s.state, rects: rectsFor(s.unit_id, s.start, s.end) })),
    ...doc.items
      .filter((i) => onPage.has(i.unit_id) && i.status !== "masked")
      .map((i) => ({ ref: i.id, kind: i.status === "open" ? i.kind : ("kept" as const), rects: rectsFor(i.unit_id, i.start, i.end) })),
  ].filter((m) => m.rects.length);
  return { index: page.index, width: page.width, height: page.height, marks };
}
