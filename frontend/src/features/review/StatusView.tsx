import { useState } from "react";
import type { DocumentSummary } from "../../api/contract";
import { isProcessing } from "../../api/queries";
import { statusDetail, statusLabel, tr } from "../../copy/tr";
import { progressFor } from "../library/filters";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { KindIcon } from "../../ui/KindIcon";
import { Progress } from "../../ui/Progress";
import { StepBar } from "../../ui/StepBar";
import { DeleteDialog } from "./DeleteDialog";
import s from "./StatusView.module.css";

/** A document that cannot be reviewed yet (processing) or at all (failed, rejected). */
export function StatusView({ doc }: { doc: DocumentSummary }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const processing = isProcessing(doc.status);
  const stage = doc.status as keyof typeof statusDetail;

  return (
    <div className={s.wrap}>
      <div className={cx(s.card, !processing && s.terminal)}>
        <KindIcon kind={doc.kind} size="lg" />
        <h1 className={s.title} title={doc.filename}>
          {doc.filename}
        </h1>
        <StepBar status={doc.status} reasons={doc.reasons} centered className={s.steps} />
        {processing ? (
          <>
            <p className={s.stage} aria-live="polite">
              {statusLabel[doc.status]}
            </p>
            <p className={s.detail}>{statusDetail[stage]}</p>
            <Progress value={progressFor(doc.status)} label={statusLabel[doc.status]} className={s.progress} />
            <p className={s.note}>
              <Icon name="shield" size={15} />
              {tr.review.processingNote}
            </p>
          </>
        ) : (
          <>
            <p className={cx(s.stage, s.stageBad)}>
              <Icon name="alert" size={16} />
              {doc.status === "failed" ? tr.review.failedTitle : tr.review.rejectedTitle}
            </p>
            {doc.reasons.length ? (
              <ul className={s.reasons}>
                {doc.reasons.map((reason) => (
                  <li key={reason.code}>{reason.text}</li>
                ))}
              </ul>
            ) : null}
            {doc.status === "rejected" ? <p className={s.detail}>{tr.review.rejectedBody}</p> : null}
            <Button variant="secondary" icon="trash" onClick={() => setConfirmDelete(true)}>
              {tr.review.delete}
            </Button>
            <DeleteDialog doc={doc} open={confirmDelete} onClose={() => setConfirmDelete(false)} />
          </>
        )}
      </div>
    </div>
  );
}
