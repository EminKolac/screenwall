import type { DecisionScope } from "../../api/contract";
import type { ReviewKeyActions } from "./useReviewKeys";
import { useReview } from "./reviewContext";
import type { SelectionMask } from "./useSelectionMask";

/** What each review shortcut does, given the current selection. */
export function useKeyActions(selectionMask: SelectionMask): ReviewKeyActions {
  const { model, selection, select, doc, decide, canDecide, canUnmask, setDialog, focusPending } = useReview();
  const selected = selection.id ? model.marks.get(selection.id) : undefined;

  const groupScope = (itemId: string): DecisionScope => {
    const group = model.pending.find((g) => g.itemIds.includes(itemId));
    return (group?.occurrences ?? 1) > 1 ? "document" : "occurrence";
  };

  const step = (direction: 1 | -1) => {
    const list = model.pendingOrder.length ? model.pendingOrder : model.order;
    if (!list.length) return;
    const at = selection.id ? list.indexOf(selection.id) : -1;
    const next = at < 0 ? (direction > 0 ? 0 : list.length - 1) : (at + direction + list.length) % list.length;
    select(list[next], "keys");
  };

  return {
    next: () => step(1),
    prev: () => step(-1),
    mask: () => {
      if (selectionMask.info) {
        void selectionMask.mask();
        return;
      }
      if (!selected || !canDecide) return;
      if (selected.state === "suggestion" || selected.state === "finding") {
        void decide({ op: "mask", target: { item_id: selected.id }, scope: groupScope(selected.id) });
      } else if (selected.state === "kept") {
        const target = selected.kind === "span" ? { span_id: selected.id } : { item_id: selected.id };
        void decide({ op: "mask", target, scope: "occurrence" });
      }
    },
    unmask: () => {
      if (!selected || !canDecide) return;
      if (selected.state === "suggestion" || selected.state === "finding") {
        void decide({ op: "keep", target: { item_id: selected.id }, scope: groupScope(selected.id) });
      } else if ((selected.state === "masked" || selected.state === "added") && canUnmask) {
        void decide({ op: "unmask", target: { span_id: selected.id }, scope: "occurrence" });
      }
    },
    approve: () => {
      if (doc.status !== "needs_review") return;
      if (doc.can.approve) setDialog("approve");
      else focusPending();
    },
    help: () => setDialog("shortcuts"),
    escape: () => {
      selectionMask.clear();
      select(null, "keys");
    },
  };
}
