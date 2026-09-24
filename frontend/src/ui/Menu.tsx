import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import { IconButton } from "./IconButton";
import s from "./Menu.module.css";

export interface MenuItem {
  id: string;
  label: string;
  icon?: IconName;
  danger?: boolean;
  onSelect: () => void;
}

interface MenuProps {
  label: string;
  items: MenuItem[];
  icon?: IconName;
  align?: "start" | "end";
}

/** Menu button (APG pattern): arrow keys move, Esc closes and returns focus. */
export function Menu({ label, items, icon = "more", align = "end" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    itemRefs.current[0]?.focus();
    const onPointer = (event: MouseEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = itemRefs.current.filter(Boolean) as HTMLButtonElement[];
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === "Tab") {
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      list[(at + step + list.length) % list.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      list[event.key === "Home" ? 0 : list.length - 1]?.focus();
    }
  };

  return (
    <div className={s.wrap} ref={wrap}>
      <IconButton
        ref={button}
        icon={icon}
        label={label}
        variant="quiet"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      />
      {open ? (
        <div id={menuId} role="menu" aria-label={label} className={cx(s.menu, s[align])} onKeyDown={onKeyDown}>
          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={cx(s.item, item.danger && s.danger)}
              onClick={() => {
                close();
                item.onSelect();
              }}
            >
              {item.icon ? <Icon name={item.icon} size={15} /> : null}
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
