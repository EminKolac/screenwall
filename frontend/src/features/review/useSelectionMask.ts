import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { guessFamily, overlapsMasked, readOriginalSelection, type TextSelectionInfo } from "./selection";
import { useReview } from "./reviewContext";

/** Tracks a text selection in the original pane and masks it on request. */
export function useSelectionMask(root: RefObject<HTMLElement | null>, toolbar: RefObject<HTMLElement | null>) {
  const { model, payload, decide, deciding, canDecide, destructive } = useReview();
  const [info, setInfo] = useState<TextSelectionInfo | null>(null);
  const [family, setFamily] = useState("PERSON");
  const [everywhere, setEverywhere] = useState(true);
  const enabled = canDecide && !destructive;

  const unitText = useCallback((unitId: string) => model.unitById.get(unitId)?.original ?? null, [model]);

  useEffect(() => {
    if (!enabled) {
      setInfo(null);
      return;
    }
    let timer = 0;
    const update = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        // While the person works inside the toolbar, keep the selection they made.
        if (toolbar.current?.contains(document.activeElement)) return;
        const next = readOriginalSelection(root.current, unitText);
        setInfo((prev) => {
          if (next && (!prev || prev.unitId !== next.unitId || prev.start !== next.start || prev.end !== next.end)) {
            setFamily(guessFamily(next.text));
          }
          return next;
        });
      }, 0);
    };
    document.addEventListener("selectionchange", update);
    document.addEventListener("mouseup", update);
    document.addEventListener("keyup", update);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("selectionchange", update);
      document.removeEventListener("mouseup", update);
      document.removeEventListener("keyup", update);
    };
  }, [enabled, root, toolbar, unitText]);

  const clear = useCallback(() => {
    window.getSelection()?.removeAllRanges();
    setInfo(null);
  }, []);

  const overlap = useMemo(
    () => (info ? overlapsMasked(payload.spans, info.unitId, info.start, info.end) : false),
    [info, payload.spans],
  );

  const mask = useCallback(async () => {
    if (!info || overlap) return;
    const ok = await decide({
      op: "mask",
      target: { unit_id: info.unitId, start: info.start, end: info.end, family },
      scope: everywhere ? "document" : "occurrence",
    });
    if (ok) clear();
  }, [info, overlap, decide, family, everywhere, clear]);

  return { info, family, setFamily, everywhere, setEverywhere, overlap, mask, clear, busy: deciding };
}

export type SelectionMask = ReturnType<typeof useSelectionMask>;
