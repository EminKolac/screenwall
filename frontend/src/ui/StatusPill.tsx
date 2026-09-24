import type { DocStatus } from "../api/contract";
import { statusLabel } from "../copy/tr";
import { cx } from "./cx";
import s from "./StatusPill.module.css";

const tone: Record<DocStatus, string> = {
  queued: s.run,
  extracting: s.run,
  masking: s.run,
  auditing: s.run,
  needs_review: s.review,
  approved: s.ok,
  rejected: s.muted,
  failed: s.danger,
};

interface StatusPillProps {
  status: DocStatus;
  /** Replaces the status word when a more specific sentence says the same thing ("2 karar bekliyor"). */
  label?: string;
  title?: string;
  className?: string;
}

export function StatusPill({ status, label, title, className }: StatusPillProps) {
  return (
    <span className={cx(s.pill, tone[status], className)} data-status={status} title={title}>
      <span className={s.dot} aria-hidden="true" />
      <span className={s.label}>{label ?? statusLabel[status]}</span>
    </span>
  );
}
