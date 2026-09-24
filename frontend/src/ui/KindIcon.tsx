import type { FileKind } from "../api/contract";
import { kindLabel } from "../copy/tr";
import { cx } from "./cx";
import s from "./KindIcon.module.css";

/** Decorative file glyph; the file name next to it already states the type. */
export function KindIcon({ kind, size = "md" }: { kind: FileKind; size?: "md" | "lg" }) {
  return (
    <span className={cx(s.kind, s[kind], size === "lg" && s.lg)} aria-hidden="true">
      <span className={s.fold} />
      <span className={s.label}>{kindLabel[kind]}</span>
    </span>
  );
}
