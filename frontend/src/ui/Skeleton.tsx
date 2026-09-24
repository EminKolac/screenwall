import type { CSSProperties } from "react";
import { cx } from "./cx";
import s from "./Skeleton.module.css";

interface SkeletonProps {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  radius?: CSSProperties["borderRadius"];
  className?: string;
}

export function Skeleton({ width = "100%", height = 12, radius, className }: SkeletonProps) {
  return <span className={cx(s.sk, className)} style={{ width, height, borderRadius: radius }} aria-hidden="true" />;
}

/** A paragraph-like stack of bars with a natural ragged edge. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  const widths = ["96%", "88%", "92%", "64%", "80%", "72%"];
  return (
    <span className={cx(s.stack, className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "58%" : widths[i % widths.length]} />
      ))}
    </span>
  );
}
