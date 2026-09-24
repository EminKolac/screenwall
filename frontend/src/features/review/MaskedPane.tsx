import type { ReviewUnit } from "../../api/contract";
import { cx } from "../../ui/cx";
import { MarkedText } from "./MarkedText";
import type { TextMark } from "./model";
import { useReview, useUnitSelection } from "./reviewContext";
import s from "./UnitText.module.css";

const NONE: TextMark[] = [];

/** The masked text of one unit: exactly what leaves in the download and goes to a model. */
export function MaskedText({ unit }: { unit: ReviewUnit }) {
  const { model, selectFromPane } = useReview();
  const selected = useUnitSelection(unit.id);
  return (
    <MarkedText
      text={unit.masked}
      marks={model.maskedMarks.get(unit.id) ?? NONE}
      selectedId={selected}
      onSelect={selectFromPane}
      chips
    />
  );
}

export function MaskedUnit({ unit }: { unit: ReviewUnit }) {
  return (
    <p className={cx(s.masked, unit.kind === "heading" && s.heading)} data-unit-masked={unit.id}>
      <MaskedText unit={unit} />
    </p>
  );
}
