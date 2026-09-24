import { useId, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { familyLabel, selectableFamilies, tr } from "../../copy/tr";
import { Icon } from "../../ui/Icon";
import type { SelectionMask } from "./useSelectionMask";
import s from "./SelectionToolbar.module.css";

interface SelectionToolbarProps {
  selection: SelectionMask;
  toolbarRef: RefObject<HTMLDivElement>;
}

const GAP = 10;
const EDGE = 8;

/** Floating "Maskele · [tür ▾] · ☐ tüm geçişler" bar above a text selection in the original pane. */
export function SelectionToolbar({ selection, toolbarRef }: SelectionToolbarProps) {
  const { info, family, setFamily, everywhere, setEverywhere, overlap, mask, clear, busy } = selection;
  const [position, setPosition] = useState({ top: EDGE, left: EDGE });
  const familyId = useId();

  useLayoutEffect(() => {
    if (!info) return;
    const place = () => {
      const rect = info.range && typeof info.range.getBoundingClientRect === "function" ? info.range.getBoundingClientRect() : null;
      const el = toolbarRef.current;
      if (!rect || !el) return;
      const width = el.offsetWidth;
      const height = el.offsetHeight;
      let top = rect.top - height - GAP;
      if (top < EDGE) top = rect.bottom + GAP;
      const left = Math.min(Math.max(EDGE, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - EDGE);
      setPosition({ top, left });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [info, toolbarRef]);

  if (!info) return null;
  return createPortal(
    <div
      ref={toolbarRef}
      role="toolbar"
      aria-label={tr.selection.label}
      className={s.toolbar}
      style={{ top: position.top, left: position.left }}
      onMouseDown={(event) => {
        // Keep the text selection alive when pressing buttons; form controls need the default.
        const target = event.target as HTMLElement;
        if (!target.closest("select, input, label")) event.preventDefault();
      }}
    >
      <span className={s.quote} title={info.text}>
        {info.text}
      </span>
      <button type="button" className={s.mask} disabled={overlap || busy} onClick={() => void mask()}>
        <Icon name="eyeOff" size={14} />
        {tr.selection.mask}
      </button>
      <span className={s.sep} aria-hidden="true" />
      <label className="sr-only" htmlFor={familyId}>
        {tr.selection.family}
      </label>
      <span className={s.selectWrap}>
        <select id={familyId} className={s.select} value={family} onChange={(event) => setFamily(event.target.value)}>
          {selectableFamilies.map((f) => (
            <option key={f} value={f}>
              {familyLabel(f)}
            </option>
          ))}
        </select>
        <Icon name="chevronDown" size={12} className={s.chevron} />
      </span>
      <label className={s.check}>
        <input type="checkbox" checked={everywhere} onChange={(event) => setEverywhere(event.target.checked)} />
        {tr.selection.allOccurrences}
      </label>
      <button type="button" className={s.close} aria-label={tr.selection.close} title={tr.selection.close} onClick={clear}>
        <Icon name="x" size={14} />
      </button>
      {overlap ? (
        <p className={s.warn} role="status">
          {tr.selection.overlap}
        </p>
      ) : null}
    </div>,
    document.body,
  );
}
