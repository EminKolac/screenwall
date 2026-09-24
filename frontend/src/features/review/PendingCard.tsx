import { useId, useState } from "react";
import { familyLabel, tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import type { PendingGroup } from "./groups";
import { useReview } from "./reviewContext";
import s from "./FindingsPanel.module.css";

/** One decision: a suggestion or an auditor finding, possibly repeated in the document. */
export function PendingCard({ group }: { group: PendingGroup }) {
  const { decide, deciding, canDecide, selection, select } = useReview();
  const [everywhere, setEverywhere] = useState(true);
  const [busy, setBusy] = useState<"mask" | "keep" | null>(null);
  const titleId = useId();
  const selected = selection.id !== null && group.itemIds.includes(selection.id);
  const repeated = group.occurrences > 1;

  const act = async (op: "mask" | "keep") => {
    setBusy(op);
    const target = selected && selection.id ? selection.id : group.itemIds[0];
    await decide({ op, target: { item_id: target }, scope: repeated && everywhere ? "document" : "occurrence" });
    setBusy(null);
  };

  return (
    <article
      className={cx(s.card, selected && s.cardSelected)}
      data-pending-card=""
      data-ids={group.itemIds.join(" ")}
      aria-labelledby={titleId}
    >
      <button type="button" id={titleId} className={s.cardText} onClick={() => select(group.itemIds[0], "panel")}>
        <mark className={s.sugMark}>{group.text}</mark>
      </button>
      <p className={s.cardMeta}>
        <Badge tone="warn">{group.kind === "finding" ? tr.findings.finding : tr.findings.suggestion}</Badge>
        <span>{familyLabel(group.family)}</span>
        {repeated ? <span className={s.dim}>· {tr.findings.occurrences(group.occurrences)}</span> : null}
      </p>
      <p className={s.reason}>{group.reason}</p>
      {canDecide ? (
        <>
          {repeated ? (
            <label className={s.scope}>
              <input type="checkbox" checked={everywhere} onChange={(event) => setEverywhere(event.target.checked)} />
              {tr.findings.allOccurrences(group.occurrences)}
            </label>
          ) : null}
          <div className={s.cardActions}>
            <Button
              size="sm"
              variant="accent"
              icon="eyeOff"
              data-action="mask"
              loading={busy === "mask"}
              disabled={deciding && busy === null}
              onClick={() => void act("mask")}
            >
              {tr.findings.mask}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              loading={busy === "keep"}
              disabled={deciding && busy === null}
              onClick={() => void act("keep")}
            >
              {tr.findings.keep}
            </Button>
          </div>
        </>
      ) : null}
    </article>
  );
}
