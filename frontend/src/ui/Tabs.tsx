import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./cx";
import s from "./Tabs.module.css";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  badge?: ReactNode;
}

interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  idBase: string;
  className?: string;
}

export const tabId = (base: string, id: string) => `${base}-tab-${id}`;
export const panelId = (base: string, id: string) => `${base}-panel-${id}`;

/** WAI-ARIA tabs with roving focus and automatic activation. */
export function Tabs<T extends string>({ items, value, onChange, label, idBase, className }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = items.length - 1;
    const next =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (next === null) return;
    event.preventDefault();
    refs.current[next]?.focus();
    onChange(items[next].id);
  };

  return (
    <div role="tablist" aria-label={label} className={cx(s.list, className)}>
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="tab"
            id={tabId(idBase, item.id)}
            aria-selected={selected}
            aria-controls={selected ? panelId(idBase, item.id) : undefined}
            tabIndex={selected ? 0 : -1}
            className={s.tab}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            <span>{item.label}</span>
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}
