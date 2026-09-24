import { tr } from "../../copy/tr";
import { Segmented } from "../../ui/Segmented";
import { NARROW_QUERY, useMediaQuery } from "../../ui/useMediaQuery";
import { useReview, type PaneId, type ViewMode } from "./reviewContext";
import s from "./SplitView.module.css";

/** Column titles for the two panes; on phones they become a pane switch. */
export function PaneHeads() {
  const { payload, view, setView, pane, setPane, destructive } = useReview();
  const narrow = useMediaQuery(NARROW_QUERY);
  const hasPages = payload.pages.length > 0 && !destructive;

  const viewToggle = hasPages ? (
    <Segmented<ViewMode>
      size="sm"
      label={tr.review.panes.viewLabel}
      value={view}
      onChange={setView}
      options={[
        { value: "text", label: tr.review.panes.text, icon: "text" },
        { value: "page", label: tr.review.panes.page, icon: "page" },
      ]}
    />
  ) : null;

  if (narrow) {
    return (
      <div className={s.headsNarrow}>
        {destructive ? null : (
          <Segmented<PaneId>
            block
            label={tr.review.panes.switchLabel}
            value={pane}
            onChange={setPane}
            options={[
              { value: "original", label: tr.review.panes.original },
              { value: "masked", label: tr.review.panes.masked },
            ]}
          />
        )}
        {pane === "original" ? viewToggle : null}
      </div>
    );
  }

  return (
    <div className={s.heads} data-view={hasPages ? view : "text"}>
      <div className={s.head}>
        <span className={s.headTitle}>{tr.review.panes.original}</span>
        {destructive ? null : <span className={s.headHint}>{tr.review.panes.originalHint}</span>}
        <span className={s.headTools}>{viewToggle}</span>
      </div>
      <div className={s.head}>
        <span className={s.headTitle}>{tr.review.panes.masked}</span>
        <span className={s.headHint}>{tr.review.panes.maskedHint}</span>
      </div>
    </div>
  );
}
