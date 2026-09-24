import { useEffect, useRef } from "react";

export interface ReviewKeyActions {
  next: () => void;
  prev: () => void;
  mask: () => void;
  unmask: () => void;
  approve: () => void;
  help: () => void;
  escape: () => void;
}

const isEditable = (target: EventTarget | null) => {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
};

/** J/K/M/U/A/?/Esc on the review screen. Silent while typing or while a dialog is open. */
export function useReviewKeys(actions: ReviewKeyActions) {
  const latest = useRef(actions);
  latest.current = actions;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditable(event.target) || document.querySelector("dialog[open]")) return;
      const a = latest.current;
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      const handlers: Record<string, (() => void) | undefined> = {
        j: a.next,
        k: a.prev,
        m: a.mask,
        u: a.unmask,
        a: a.approve,
        "?": a.help,
        Escape: a.escape,
      };
      const handler = handlers[key];
      if (!handler) return;
      event.preventDefault();
      handler();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
