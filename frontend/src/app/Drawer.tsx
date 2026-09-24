import { useEffect, useRef, type ReactNode } from "react";
import s from "./Shell.module.css";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  label: string;
  children: ReactNode;
}

/** Slide-over panel on a native modal <dialog>: focus trap, Esc and backdrop close. */
export function Drawer({ open, onClose, label, children }: DrawerProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const openRef = useRef(open);
  const onCloseRef = useRef(onClose);
  openRef.current = open;
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
      const target = returnFocus.current;
      returnFocus.current = null;
      if (target?.isConnected) target.focus();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={s.drawer}
      aria-label={label}
      onCancel={(event) => {
        event.preventDefault();
        onCloseRef.current();
      }}
      onClose={() => {
        if (openRef.current) onCloseRef.current();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onCloseRef.current();
      }}
    >
      <div className={s.drawerInner}>{children}</div>
    </dialog>
  );
}
