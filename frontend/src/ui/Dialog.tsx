import { useEffect, useId, useRef, type MouseEvent, type ReactNode, type RefObject } from "react";
import { tr } from "../copy/tr";
import { cx } from "./cx";
import { IconButton } from "./IconButton";
import s from "./Dialog.module.css";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Element to focus when the dialog opens; defaults to the browser's first focusable. */
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
}

/** Native modal <dialog>: focus trap, Esc and inert background for free; focus returns on close. */
export function Dialog({ open, onClose, title, description, children, footer, size = "md", initialFocus, className }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const pressedBackdrop = useRef(false);
  const onCloseRef = useRef(onClose);
  const openRef = useRef(open);
  onCloseRef.current = onClose;
  openRef.current = open;
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) {
        const active = document.activeElement;
        returnFocus.current = active instanceof HTMLElement ? active : null;
        dialog.showModal();
      }
      initialFocus?.current?.focus();
    } else {
      if (dialog.open) dialog.close();
      const target = returnFocus.current;
      returnFocus.current = null;
      if (target && target.isConnected) target.focus();
    }
    // initialFocus is a stable ref object; only the open flag drives this effect.
  }, [open]);

  const onMouseDown = (event: MouseEvent<HTMLDialogElement>) => {
    pressedBackdrop.current = event.target === ref.current;
  };
  const onClick = (event: MouseEvent<HTMLDialogElement>) => {
    if (pressedBackdrop.current && event.target === ref.current) onCloseRef.current();
    pressedBackdrop.current = false;
  };

  return (
    <dialog
      ref={ref}
      className={cx(s.dialog, s[size], className)}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onCloseRef.current();
      }}
      onClose={() => {
        if (openRef.current) onCloseRef.current();
      }}
      onMouseDown={onMouseDown}
      onClick={onClick}
    >
      {open ? (
        <div className={s.frame}>
          <header className={s.head}>
            <h2 id={titleId} className={s.title}>
              {title}
            </h2>
            <IconButton icon="x" size="sm" label={tr.common.close} onClick={() => onCloseRef.current()} />
          </header>
          <div className={s.body}>
            {description ? (
              <div id={descriptionId} className={s.description}>
                {description}
              </div>
            ) : null}
            {children}
          </div>
          {footer ? <footer className={s.foot}>{footer}</footer> : null}
        </div>
      ) : null}
    </dialog>
  );
}
