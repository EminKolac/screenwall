import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { DocumentSummary } from "../../api/contract";
import { useDocuments, useReviewPayload } from "../../api/queries";
import { tr } from "../../copy/tr";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Skeleton, SkeletonText } from "../../ui/Skeleton";
import { useKeyActions } from "./keyActions";
import { WorkspaceHeader } from "./WorkspaceHeader";
import { KeysFooter } from "./KeysFooter";
import { PageView } from "./PageView";
import { PaneHeads } from "./PaneHeads";
import { ReviewDialogs } from "./ReviewDialogs";
import { ReviewProvider, useReview } from "./reviewContext";
import { SelectionToolbar } from "./SelectionToolbar";
import { SidePanel, type SideTab } from "./SidePanel";
import { SplitView } from "./SplitView";
import { StatusView } from "./StatusView";
import { useReviewKeys } from "./useReviewKeys";
import { useSelectionMask } from "./useSelectionMask";
import s from "./ReviewWorkspace.module.css";

function WorkspaceSkeleton() {
  return (
    <div className={s.workspace} aria-busy="true">
      <div className={s.center}>
        <div className={s.skeletonHead}>
          <Skeleton width="42%" height={20} />
          <Skeleton width="58%" height={12} />
        </div>
        <div className={s.skeletonBody}>
          {[0, 1].map((i) => (
            <div key={i} className={s.skeletonSheet}>
              <SkeletonText lines={4} />
              <SkeletonText lines={3} />
            </div>
          ))}
        </div>
      </div>
      <div className={s.side}>
        <div className={s.skeletonSide}>
          <Skeleton width="40%" height={12} />
          <Skeleton height={96} radius={6} />
          <Skeleton height={64} radius={6} />
        </div>
      </div>
    </div>
  );
}

function Problem({ title, body, onRetry }: { title: string; body?: string; onRetry?: () => void }) {
  return (
    <div className={s.problem}>
      <EmptyState
        title={title}
        icon="alert"
        headingLevel="h1"
        actions={
          onRetry ? (
            <Button icon="refresh" onClick={onRetry}>
              {tr.common.retry}
            </Button>
          ) : null
        }
      >
        {body}
      </EmptyState>
    </div>
  );
}

function ReviewLayout({ tab }: { tab: SideTab }) {
  const { view, payload, destructive, focusUnit, setDialog } = useReview();
  const scrollRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const selectionMask = useSelectionMask(scrollRef, toolbarRef);
  const location = useLocation();
  const navigate = useNavigate();
  useReviewKeys(useKeyActions(selectionMask));

  // A citation in another document's chat lands here with the unit to show.
  useEffect(() => {
    const unit = (location.state as { focusUnit?: string } | null)?.focusUnit;
    if (!unit) return;
    focusUnit(unit);
    navigate(location.pathname, { replace: true, state: null });
  }, [location.key]);

  const pageView = view === "page" && payload.pages.length > 0 && !destructive;
  return (
    <div className={s.workspace}>
      <section className={s.center} aria-label={tr.review.regionLabel}>
        <WorkspaceHeader />
        <div ref={scrollRef} className={s.scroll}>
          <PaneHeads />
          {pageView ? <PageView /> : <SplitView />}
        </div>
        <KeysFooter onHelp={() => setDialog("shortcuts")} />
      </section>
      <SidePanel tab={tab} />
      <SelectionToolbar selection={selectionMask} toolbarRef={toolbarRef} />
      <ReviewDialogs />
    </div>
  );
}

function ReviewLoader({ doc, tab }: { doc: DocumentSummary; tab: SideTab }) {
  const review = useReviewPayload(doc.id, true);
  if (review.isPending) return <WorkspaceSkeleton />;
  if (review.isError || !review.data) {
    return <Problem title={tr.review.loadError} onRetry={() => void review.refetch()} />;
  }
  return (
    <ReviewProvider doc={doc} payload={review.data}>
      <ReviewLayout tab={tab} />
    </ReviewProvider>
  );
}

/** Route element for /d/:id and /d/:id/sohbet. */
export function ReviewWorkspace({ docId, tab }: { docId: string; tab: SideTab }) {
  const docs = useDocuments();
  const doc = docs.data?.find((d) => d.id === docId);
  if (docs.isPending) return <WorkspaceSkeleton />;
  if (!doc) {
    if (docs.isError) return <Problem title={tr.library.loadError} onRetry={() => void docs.refetch()} />;
    return <Problem title={tr.review.notFoundTitle} body={tr.review.notFoundBody} />;
  }
  if (!doc.can.review) return <StatusView doc={doc} />;
  return <ReviewLoader doc={doc} tab={tab} />;
}
