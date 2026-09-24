import type { ReviewUnit } from "../../api/contract";
import { tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { MarkedText } from "./MarkedText";
import type { TextMark } from "./model";
import { useReview, useUnitSelection } from "./reviewContext";
import s from "./UnitText.module.css";
import p from "./SplitView.module.css";

const NONE: TextMark[] = [];

/** The original text of one unit. Text selection here is what the selection toolbar masks. */
export function OriginalText({ unit }: { unit: ReviewUnit }) {
  const { model, selectFromPane } = useReview();
  const selected = useUnitSelection(unit.id);
  if (unit.original === null) return null;
  return (
    <MarkedText
      text={unit.original}
      marks={model.originalMarks.get(unit.id) ?? NONE}
      selectedId={selected}
      onSelect={selectFromPane}
      focusable
      strikeKept
    />
  );
}

export function OriginalUnit({ unit }: { unit: ReviewUnit }) {
  return (
    <p className={cx(s.original, unit.kind === "heading" && s.heading)} data-unit-text={unit.id}>
      <OriginalText unit={unit} />
    </p>
  );
}

/** Shown instead of the original in destructive mode: there is nothing to show, by design. */
export function DestructiveNotice() {
  return (
    <div className={p.notice}>
      <span className={p.noticeIcon} aria-hidden="true">
        <Icon name="lock" size={18} />
      </span>
      <h2 className={p.noticeTitle}>
        {tr.review.destructive.title}
      </h2>
      <p className={p.noticeBody}>{tr.review.destructive.body}</p>
    </div>
  );
}
