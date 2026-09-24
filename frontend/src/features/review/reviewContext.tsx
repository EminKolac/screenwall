import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import type { DecisionRequest, DocumentSummary, ReviewPayload } from "../../api/contract";
import { useDecide } from "../../api/queries";
import { tr } from "../../copy/tr";
import { useToast } from "../../ui/Toast";
import { buildModel, type ReviewModel } from "./model";
import { reviewFailureToast } from "./reviewToast";

/** Where a selection came from: every other surface scrolls to it, the origin stays put. */
export type SelectSource = "pane" | "panel" | "keys" | "page";
export type ReviewDialog = "approve" | "reject" | "delete" | "shortcuts";
export type ViewMode = "text" | "page";
export type PaneId = "original" | "masked";

export interface Selection {
  id: string | null;
  source: SelectSource;
  nonce: number;
}

/** What callers decide; the provider pins it to the revision of the payload on screen. */
export type ReviewDecision = Omit<DecisionRequest, "expected_revision">;

interface ReviewState {
  doc: DocumentSummary;
  payload: ReviewPayload;
  model: ReviewModel;
  destructive: boolean;
  canDecide: boolean;
  canUnmask: boolean;
  selection: Selection;
  select: (id: string | null, source: SelectSource) => void;
  selectFromPane: (id: string) => void;
  decide: (request: ReviewDecision) => Promise<boolean>;
  deciding: boolean;
  view: ViewMode;
  setView: (view: ViewMode) => void;
  page: number;
  setPage: (page: number) => void;
  pane: PaneId;
  setPane: (pane: PaneId) => void;
  unitFocus: { unitId: string; nonce: number } | null;
  focusUnit: (unitId: string) => void;
  pendingFocus: number;
  focusPending: () => void;
  dialog: ReviewDialog | null;
  setDialog: (dialog: ReviewDialog | null) => void;
}

const ReviewContext = createContext<ReviewState | null>(null);

interface ProviderProps {
  doc: DocumentSummary;
  payload: ReviewPayload;
  children: ReactNode;
}

export function ReviewProvider({ doc, payload, children }: ProviderProps) {
  const toast = useToast();
  const mutation = useDecide(doc.id);
  const model = useMemo(() => buildModel(payload), [payload]);
  const nonce = useRef(0);
  const [selection, setSelection] = useState<Selection>({ id: null, source: "keys", nonce: 0 });
  const [view, setView] = useState<ViewMode>("text");
  const [page, setPageState] = useState(payload.pages[0]?.index ?? 1);
  const [pane, setPane] = useState<PaneId>("original");
  const [unitFocus, setUnitFocus] = useState<{ unitId: string; nonce: number } | null>(null);
  const [pendingFocus, setPendingFocus] = useState(0);
  const [dialog, setDialog] = useState<ReviewDialog | null>(null);

  const destructive = doc.mode === "destructive" || payload.units.every((u) => u.original === null);
  const canDecide = doc.can.decide;
  const pageCount = payload.pages.length;

  const setPage = useCallback(
    (next: number) => setPageState(Math.min(Math.max(1, next), Math.max(1, pageCount))),
    [pageCount],
  );

  const select = useCallback(
    (id: string | null, source: SelectSource) => {
      setSelection({ id, source, nonce: ++nonce.current });
      const unit = id ? model.unitById.get(model.marks.get(id)?.unitId ?? "") : undefined;
      if (unit?.page) setPageState(unit.page);
    },
    [model],
  );

  const selectFromPane = useCallback((id: string) => select(id, "pane"), [select]);

  // Every decision carries the revision its span/item ids were read from, so none can hit the wrong span.
  const revision = payload.document.revision;
  const decide = useCallback(
    async (request: ReviewDecision) => {
      try {
        const next = await mutation.mutateAsync({ ...request, expected_revision: revision });
        toast.show(tr.common.saved);
        if ("item_id" in request.target) {
          // Guide the person to the next open decision.
          const upcoming = buildModel(next).pendingOrder[0] ?? null;
          setSelection({ id: upcoming, source: "keys", nonce: ++nonce.current });
        }
        return true;
      } catch (error) {
        toast.show(reviewFailureToast(error));
        return false;
      }
    },
    [mutation, toast, revision],
  );

  const focusUnit = useCallback((unitId: string) => {
    setView("text");
    setPane("masked");
    setUnitFocus({ unitId, nonce: ++nonce.current });
  }, []);

  const focusPending = useCallback(() => {
    const first = model.pendingOrder[0];
    if (first) setSelection({ id: first, source: "keys", nonce: ++nonce.current });
    setPendingFocus((n) => n + 1);
  }, [model]);

  const value = useMemo<ReviewState>(
    () => ({
      doc,
      payload,
      model,
      destructive,
      canDecide,
      canUnmask: canDecide && !destructive,
      selection,
      select,
      selectFromPane,
      decide,
      deciding: mutation.isPending,
      view,
      setView,
      page,
      setPage,
      pane,
      setPane,
      unitFocus,
      focusUnit,
      pendingFocus,
      focusPending,
      dialog,
      setDialog,
    }),
    [doc, payload, model, destructive, canDecide, selection, select, selectFromPane, decide, mutation.isPending,
      view, page, setPage, pane, unitFocus, focusUnit, pendingFocus, focusPending, dialog],
  );

  return <ReviewContext.Provider value={value}>{children}</ReviewContext.Provider>;
}

export function useReview(): ReviewState {
  const ctx = useContext(ReviewContext);
  if (!ctx) throw new Error("useReview needs <ReviewProvider>");
  return ctx;
}

/** The selected id if it belongs to this unit, else null: keeps other units' memoised text still. */
export function useUnitSelection(unitId: string): string | null {
  const { selection, model } = useReview();
  return selection.id && model.marks.get(selection.id)?.unitId === unitId ? selection.id : null;
}
