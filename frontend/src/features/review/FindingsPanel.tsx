import { useEffect, useId, useRef } from "react";
import { useHealth } from "../../api/queries";
import { tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Icon } from "../../ui/Icon";
import { KeptList } from "./KeptList";
import { MaskedList } from "./MaskedList";
import { PendingCard } from "./PendingCard";
import { useReview } from "./reviewContext";
import s from "./FindingsPanel.module.css";

const behavior = (): ScrollBehavior =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

export function FindingsPanel() {
  const { model, doc, canDecide, selection, pendingFocus } = useReview();
  const health = useHealth();
  const root = useRef<HTMLDivElement>(null);
  const pendingId = useId();
  const maskedId = useId();
  const pendingCount = model.pendingOrder.length;
  const maskedCount = model.masked.reduce((n, g) => n + g.count, 0);

  // Follow selections made in the text or with J/K.
  useEffect(() => {
    if (!selection.id || selection.source === "panel") return;
    const target = root.current?.querySelector<HTMLElement>(`[data-ids~="${selection.id}"]`);
    target?.scrollIntoView?.({ block: "nearest", behavior: behavior() });
  }, [selection.nonce, selection.id, selection.source]);

  // "Onayla" while decisions are open: bring the first one to the keyboard.
  useEffect(() => {
    if (!pendingFocus) return;
    const action = root.current?.querySelector<HTMLButtonElement>('[data-pending-card] [data-action="mask"]');
    action?.scrollIntoView?.({ block: "nearest", behavior: behavior() });
    action?.focus({ preventScroll: true });
  }, [pendingFocus]);

  const auditor = health.data?.auditor;

  return (
    <div ref={root} className={s.panel}>
      {!canDecide && doc.status === "approved" ? (
        <p className={s.readOnly}>
          <Icon name="lock" size={14} />
          {tr.review.readOnly}
        </p>
      ) : null}

      {canDecide || pendingCount ? (
        <section className={s.group} aria-labelledby={pendingId}>
          <h2 id={pendingId} className={s.groupTitle}>
            {tr.findings.pendingTitle}
            <Badge tone={pendingCount ? "warn" : "count"}>{pendingCount}</Badge>
          </h2>
          {model.pending.length ? (
            <div className={s.cards}>
              {model.pending.map((group) => (
                <PendingCard key={group.key} group={group} />
              ))}
            </div>
          ) : (
            <p className={s.allClear}>
              <Icon name="check" size={15} />
              {tr.findings.pendingEmpty}
            </p>
          )}
        </section>
      ) : null}

      <section className={s.group} aria-labelledby={maskedId}>
        <h2 id={maskedId} className={s.groupTitle}>
          {tr.findings.maskedTitle}
          <Badge tone="count">{maskedCount}</Badge>
        </h2>
        <MaskedList />
      </section>

      <KeptList />

      {auditor ? (
        <p className={s.audit}>
          <Icon name="shield" size={14} />
          {auditor.reachable ? tr.findings.auditFooter(auditor.model) : tr.findings.auditOffline}
        </p>
      ) : null}
    </div>
  );
}
