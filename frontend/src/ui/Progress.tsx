import { cx } from "./cx";
import s from "./Progress.module.css";

interface ProgressProps {
  value: number;
  label: string;
  className?: string;
}

export function Progress({ value, label, className }: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <span
      className={cx(s.track, className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
    >
      <span className={s.fill} style={{ width: `${clamped}%` }} />
    </span>
  );
}
