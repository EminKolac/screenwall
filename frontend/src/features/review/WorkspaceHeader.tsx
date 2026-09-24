import { useId } from "react";
import { Link } from "react-router-dom";
import { modeText, tr } from "../../copy/tr";
import { docPath } from "../../app/paths";
import { Badge } from "../../ui/Badge";
import { Button, buttonClass } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { KindIcon } from "../../ui/KindIcon";
import { Menu } from "../../ui/Menu";
import { StepBar } from "../../ui/StepBar";
import { useReview } from "./reviewContext";
import { useDownload } from "./useDownload";
import s from "./WorkspaceHeader.module.css";

export function WorkspaceHeader() {
  const { doc, destructive, setDialog, focusPending } = useReview();
  const download = useDownload(doc);
  const gateId = useId();
  const reviewing = doc.status === "needs_review";
  const blocked = reviewing && !doc.can.approve;
  const pending = doc.counts.pending;
  const menu = [{ id: "delete", label: tr.review.delete, icon: "trash" as const, danger: true, onSelect: () => setDialog("delete") }];

  return (
    <header className={s.header}>
      <div className={s.titleRow}>
        <KindIcon kind={doc.kind} />
        <h1 className={s.title} title={doc.filename}>
          {doc.filename}
        </h1>
        <Badge tone={destructive ? "strong" : "neutral"} icon={destructive ? "lock" : "key"} title={modeText[doc.mode].consequence}>
          {modeText[doc.mode].label}
        </Badge>
      </div>

      <StepBar status={doc.status} reasons={doc.reasons} className={s.steps} />

      <div className={s.actions}>
        {reviewing ? (
          <>
            <Button variant="quiet" onClick={() => setDialog("reject")}>
              {tr.review.reject}
            </Button>
            <Menu label={tr.review.more} items={menu} />
            <Button
              variant="primary"
              icon="check"
              aria-describedby={gateId}
              onClick={() => (blocked ? focusPending() : setDialog("approve"))}
            >
              {tr.review.approve}
            </Button>
          </>
        ) : null}
        {doc.status === "approved" ? (
          <>
            <Menu label={tr.review.more} items={menu} />
            {doc.can.chat ? (
              <Link to={docPath(doc.id, true)} className={buttonClass("secondary")}>
                <Icon name="chat" size={16} />
                {tr.review.chat}
              </Link>
            ) : null}
            <Button variant="primary" icon="download" loading={download.pending} disabled={!doc.can.download} onClick={() => void download.start()}>
              {download.pending ? tr.review.downloading : tr.review.download}
            </Button>
          </>
        ) : null}
      </div>

      {reviewing ? (
        <p id={gateId} className={cx(s.gate, blocked ? s.gateBlocked : s.gateReady)} aria-live="polite">
          <Icon name={blocked ? "alert" : "check"} size={14} />
          {blocked ? tr.review.blocked(pending) : tr.review.ready}
        </p>
      ) : null}

      {reviewing && doc.reasons.length ? (
        <ul className={s.reasons} aria-label={tr.review.reasonsTitle}>
          {doc.reasons.map((reason) => (
            <li key={reason.code}>
              <Icon name="info" size={15} />
              {reason.text}
            </li>
          ))}
        </ul>
      ) : null}
    </header>
  );
}
