import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { tr } from "../copy/tr";
import { cx } from "./cx";
import { Icon } from "./Icon";
import s from "./Toast.module.css";

type ToastTone = "ok" | "error" | "info";

export interface ToastInput {
  message: string;
  tone?: ToastTone;
  action?: { label: string; onClick: () => void };
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

interface ToastApi {
  show: (input: ToastInput | string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
const ICON = { ok: "check", error: "alert", info: "info" } as const;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (input: ToastInput | string) => {
      const toast = typeof input === "string" ? { message: input } : input;
      const id = ++seq.current;
      setItems((prev) => [...prev.slice(-2), { ...toast, id }]);
      const duration = toast.duration ?? (toast.tone === "error" ? 6500 : toast.action ? 6000 : 3200);
      window.setTimeout(() => dismiss(id), duration);
    },
    [dismiss],
  );

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <section className={s.region} aria-label={tr.common.notifications}>
        <ol className={s.list} aria-live="polite" aria-relevant="additions text">
          {items.map((toast) => {
            const tone = toast.tone ?? "ok";
            return (
              <li key={toast.id} className={cx(s.toast, s[tone])}>
                <span className={s.icon}>
                  <Icon name={ICON[tone]} size={16} />
                </span>
                <span className={s.message}>{toast.message}</span>
                {toast.action ? (
                  <button
                    type="button"
                    className={s.action}
                    onClick={() => {
                      toast.action?.onClick();
                      dismiss(toast.id);
                    }}
                  >
                    {toast.action.label}
                  </button>
                ) : null}
                <button type="button" className={s.close} aria-label={tr.common.dismiss} onClick={() => dismiss(toast.id)}>
                  <Icon name="x" size={14} />
                </button>
              </li>
            );
          })}
        </ol>
      </section>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast needs <ToastProvider>");
  return ctx;
}
