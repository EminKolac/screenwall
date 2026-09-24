import { Fragment, memo, useMemo, type KeyboardEvent } from "react";
import { familyLabel, tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import type { MarkState, TextMark } from "./model";
import { chars } from "./text";
import s from "./MarkedText.module.css";

// When ranges overlap, the one that needs attention wins.
const PRIORITY: Record<MarkState, number> = { suggestion: 4, finding: 4, added: 3, masked: 2, kept: 1 };

export interface Segment {
  text: string;
  mark: TextMark | null;
}

/** Split `text` at every mark boundary (code points), merging neighbours won by the same mark. */
export function segment(text: string, marks: TextMark[]): Segment[] {
  const cps = chars(text);
  const valid = marks.filter(
    (m) => Number.isInteger(m.start) && Number.isInteger(m.end) && m.start >= 0 && m.end <= cps.length && m.start < m.end,
  );
  const cuts = [...new Set([0, cps.length, ...valid.flatMap((m) => [m.start, m.end])])].sort((a, b) => a - b);
  const out: Segment[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const from = cuts[i];
    const to = cuts[i + 1];
    const winner =
      valid
        .filter((m) => m.start <= from && m.end > from)
        .sort((a, b) => PRIORITY[b.state] - PRIORITY[a.state])[0] ?? null;
    const piece = cps.slice(from, to).join("");
    const last = out[out.length - 1];
    if (last && last.mark === winner) last.text += piece;
    else out.push({ text: piece, mark: winner });
  }
  return out;
}

interface MarkedTextProps {
  text: string;
  marks: TextMark[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Masked pane: placeholders render as compact monospace chips. */
  chips?: boolean;
  /** Put interactive marks in the tab order (the original pane does, the masked pane mirrors). */
  focusable?: boolean;
  /** Draw the kept state with a strike (original pane only; in the output the text is simply visible). */
  strikeKept?: boolean;
}

export const MarkedText = memo(function MarkedText({
  text,
  marks,
  selectedId,
  onSelect,
  chips = false,
  focusable = false,
  strikeKept = false,
}: MarkedTextProps) {
  const parts = useMemo(() => segment(text, marks), [text, marks]);
  return (
    <>
      {parts.map((part, index) => {
        const mark = part.mark;
        if (!mark) return <Fragment key={index}>{part.text}</Fragment>;
        const family = familyLabel(mark.family);
        const interactive = Boolean(onSelect);
        const chip = chips && (mark.state === "masked" || mark.state === "added");
        const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect?.(mark.id);
          }
        };
        return (
          <mark
            key={index}
            className={cx(
              s.mark,
              s[mark.state],
              chip && s.chip,
              strikeKept && mark.state === "kept" && s.strike,
              selectedId === mark.id && s.selected,
            )}
            data-mark-id={mark.id}
            data-state={mark.state}
            title={mark.reason ? `${family} · ${mark.reason}` : family}
            role={interactive ? "button" : undefined}
            tabIndex={interactive ? (focusable ? 0 : -1) : undefined}
            aria-label={interactive ? tr.marks.aria(part.text, family, tr.marks[mark.state]) : undefined}
            onClick={interactive ? () => onSelect?.(mark.id) : undefined}
            onKeyDown={interactive ? onKeyDown : undefined}
          >
            {part.text}
          </mark>
        );
      })}
    </>
  );
});
