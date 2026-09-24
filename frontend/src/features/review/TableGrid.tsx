import type { ReviewUnit } from "../../api/contract";
import { tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import { MaskedText } from "./MaskedPane";
import type { TableBlock } from "./model";
import { OriginalText } from "./OriginalPane";
import type { PaneId } from "./reviewContext";
import s from "./UnitText.module.css";

export type TableSide = PaneId | "both";

/**
 * One cell. With side "both" the original sits on top and the masked value below it, shown
 * only when the two differ, so a spreadsheet keeps its full width instead of being split in two.
 */
function CellContent({ unit, side }: { unit: ReviewUnit; side: TableSide }) {
  const hasOriginal = unit.original !== null;
  const same = hasOriginal && unit.original === unit.masked;
  if (side === "masked" || !hasOriginal) {
    return (
      <span className={s.part} data-unit-masked={unit.id}>
        <MaskedText unit={unit} />
      </span>
    );
  }
  if (side === "original" || same) {
    return (
      <span className={s.part} data-pane="original" data-unit-text={unit.id} data-unit-masked={same ? unit.id : undefined}>
        <OriginalText unit={unit} />
      </span>
    );
  }
  return (
    <>
      <span className={cx(s.part, s.partOriginal)} data-pane="original" data-unit-text={unit.id}>
        <OriginalText unit={unit} />
      </span>
      <span className={cx(s.part, s.partMasked)} data-pane="masked" data-unit-masked={unit.id}>
        <MaskedText unit={unit} />
      </span>
    </>
  );
}

export function TableGrid({ block, side }: { block: TableBlock; side: TableSide }) {
  const [head, ...body] = block.rows;
  const cell = (unit: ReviewUnit | null) => (unit ? <CellContent unit={unit} side={side} /> : null);
  return (
    <div className={s.tableWrap}>
      <table className={cx(s.table, side === "masked" ? s.maskedTable : s.originalTable, side === "both" && s.bothTable)}>
        <caption className={s.caption}>
          {tr.review.table(block.index)}
          {side === "both" ? <span className={s.captionHint}>{tr.review.tableHint}</span> : null}
        </caption>
        <thead>
          <tr>
            {head.map((unit, col) => (
              <th key={col} scope="col">
                {cell(unit)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, r) => (
            <tr key={r}>
              {row.map((unit, col) => (
                <td key={col}>{cell(unit)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
