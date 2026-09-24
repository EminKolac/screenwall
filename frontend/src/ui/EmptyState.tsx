import type { ReactNode } from "react";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import s from "./EmptyState.module.css";

interface EmptyStateProps {
  title: string;
  children?: ReactNode;
  icon?: IconName;
  art?: ReactNode;
  actions?: ReactNode;
  hint?: ReactNode;
  headingLevel?: "h1" | "h2" | "h3";
  size?: "md" | "lg";
  tone?: "neutral" | "danger";
  className?: string;
}

export function EmptyState({
  title,
  children,
  icon = "file",
  art,
  actions,
  hint,
  headingLevel = "h2",
  size = "md",
  tone = "neutral",
  className,
}: EmptyStateProps) {
  const Heading = headingLevel;
  return (
    <div className={cx(s.empty, s[size], tone === "danger" && s.danger, className)}>
      {art ?? (
        <span className={s.icon} aria-hidden="true">
          <Icon name={icon} size={size === "lg" ? 26 : 20} />
        </span>
      )}
      <Heading className={s.title}>{title}</Heading>
      {children ? <div className={s.body}>{children}</div> : null}
      {actions ? <div className={s.actions}>{actions}</div> : null}
      {hint ? <p className={s.hint}>{hint}</p> : null}
    </div>
  );
}
