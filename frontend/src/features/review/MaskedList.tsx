import { useState } from "react";
import type { DecisionScope } from "../../api/contract";
import { tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Segmented } from "../../ui/Segmented";
import type { MaskedEntry } from "./groups";
import { useReview } from "./reviewContext";
import s from "./FindingsPanel.module.css";

function MaskedRow({ entry }: { entry: MaskedEntry }) {
  const { selection, select, decide, deciding, canUnmask, canDecide, destructive } = useReview();
  const [scope, setScope] = useState<Extract<DecisionScope, "occurrence" | "document">>("occurrence");
  const [busy, setBusy] = useState<DecisionScope | null>(null);
  const selected = selection.id !== null && entry.spanIds.includes(selection.id);
  const target = selected && selection.id ? selection.id : entry.spanIds[0];
  const count = entry.spanIds.length;

  const unmask = async (chosen: DecisionScope) => {
    setBusy(chosen);
    await decide({ op: "unmask", target: { span_id: target }, scope: chosen });
    setBusy(null);
  };

  return (
    <li className={cx(s.row, selected && s.rowSelected)} data-ids={entry.spanIds.join(" ")}>
      <button type="button" className={s.rowMain} aria-expanded={selected} onClick={() => select(target, "panel")}>
        {entry.known ? (
          <>
            <span className={s.surface}>{entry.surface}</span>
            <span className={s.placeholder}>{entry.placeholder}</span>
          </>
        ) : (
          <span className={s.surface}>
            <span className={s.placeholder}>{entry.placeholder}</span>
          </span>
        )}
        <span className={s.why}>
          {entry.reason}
          {count > 1 ? ` · ${tr.findings.occurrences(count)}` : ""}
        </span>
      </button>
      {entry.added ? (
        <Badge tone="info" icon="plus" className={s.addedBadge}>
          {tr.findings.addedByYou}
        </Badge>
      ) : null}
      {selected && canDecide ? (
        <div className={s.rowActions}>
          {canUnmask ? (
            <>
              {count > 1 ? (
                <Segmented
                  size="sm"
                  block
                  label={tr.findings.scopeLabel}
                  value={scope}
                  onChange={setScope}
                  options={[
                    { value: "occurrence", label: tr.findings.scopeOccurrence },
                    { value: "document", label: tr.findings.scopeDocument },
                  ]}
                />
              ) : null}
              <div className={s.rowButtons}>
                <Button
                  size="sm"
                  variant="secondary"
                  icon="eye"
                  loading={busy === scope}
                  disabled={deciding && busy === null}
                  onClick={() => void unmask(scope)}
                >
                  {tr.findings.unmask}
                </Button>
                <Button
                  size="sm"
                  variant="link"
                  loading={busy === "global"}
                  disabled={deciding && busy === null}
                  title={tr.findings.neverMaskHint}
                  onClick={() => void unmask("global")}
                >
                  {tr.findings.neverMask}
                </Button>
              </div>
            </>
          ) : (
            <p className={s.why}>{destructive ? tr.findings.destructiveNoUnmask : tr.review.readOnly}</p>
          )}
        </div>
      ) : null}
    </li>
  );
}

/** Masked values grouped by family, one row per distinct value. */
export function MaskedList() {
  const { model } = useReview();
  if (!model.masked.length) return <p className={s.empty}>{tr.findings.maskedEmpty}</p>;
  return (
    <div className={s.families}>
      {model.masked.map((group) => (
        <div key={group.family} className={s.family}>
          <h3 className={s.familyTitle}>
            {group.label}
            <span className={s.familyCount}>{group.count}</span>
          </h3>
          <ul className={s.rows}>
            {group.entries.map((entry) => (
              <MaskedRow key={entry.key} entry={entry} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
