import type { ReactNode } from "react";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import s from "./Badge.module.css";

export type BadgeTone = "neutral" | "ok" | "warn" | "info" | "danger" | "strong" | "count";

interface BadgeProps {
  tone?: BadgeTone;
  icon?: IconName;
  children: ReactNode;
  className?: string;
  title?: string;
}

export function Badge({ tone = "neutral", icon, children, className, title }: BadgeProps) {
  return (
    <span className={cx(s.badge, s[tone], className)} title={title}>
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}
