import { useEffect, useState } from "react";
import { familyLabel, tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { useReview } from "./reviewContext";
import s from "./FindingsPanel.module.css";

/** Values the person chose to leave visible; collapsed unless one of them is selected. */
export function KeptList() {
  const { model, selection, select, decide, deciding, canDecide } = useReview();
  const [open, setOpen] = useState(false);
  const entries = model.kept;

  useEffect(() => {
    if (selection.id && entries.some((e) => e.spanIds.includes(selection.id!) || e.itemIds.includes(selection.id!))) {
      setOpen(true);
    }
  }, [selection.nonce, selection.id, entries]);

  if (!entries.length) return null;
  return (
    <details className={s.kept} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={s.keptSummary}>
        {tr.findings.keptTitle}
        <Badge tone="count">{entries.length}</Badge>
      </summary>
      <ul className={s.rows}>
        {entries.map((entry) => {
          const ids = [...entry.spanIds, ...entry.itemIds];
          const selected = selection.id !== null && ids.includes(selection.id);
          const target = entry.spanIds[0] ? { span_id: entry.spanIds[0] } : { item_id: entry.itemIds[0] };
          return (
            <li key={entry.key} className={cx(s.row, selected && s.rowSelected)} data-ids={ids.join(" ")}>
              <button type="button" className={s.rowMain} onClick={() => select(ids[0], "panel")}>
                <span className={s.keptSurface}>{entry.surface}</span>
                <span className={s.why}>
                  {familyLabel(entry.family)} · {entry.reason}
                </span>
              </button>
              {canDecide ? (
                <div className={s.rowButtons}>
                  <Button
                    size="sm"
                    variant="quiet"
                    icon="undo"
                    disabled={deciding}
                    onClick={() => void decide({ op: "mask", target, scope: "occurrence" })}
                  >
                    {tr.findings.remask}
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
