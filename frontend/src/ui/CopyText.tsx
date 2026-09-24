import { tr } from "../copy/tr";
import { cx } from "./cx";
import { IconButton } from "./IconButton";
import { useToast } from "./Toast";
import s from "./CopyText.module.css";

/** Shows a command as copyable text. The app never runs it. */
export function CopyText({ text, className }: { text: string; className?: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.show(tr.common.copied);
    } catch {
      toast.show({ message: tr.common.copyFailed, tone: "error" });
    }
  };
  return (
    <span className={cx(s.copy, className)}>
      <code className={s.code}>{text}</code>
      <IconButton icon="copy" size="sm" label={tr.common.copyCommand(text)} onClick={copy} />
    </span>
  );
}
