import { useRef, type KeyboardEvent } from "react";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import s from "./Segmented.module.css";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
  disabled?: boolean;
}

interface SegmentedProps<T extends string> {
  label: string;
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  block?: boolean;
  className?: string;
}

/** A radio group drawn as a segmented control (roving focus, arrow keys). */
export function Segmented<T extends string>({ label, options, value, onChange, size = "md", block, className }: SegmentedProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabled = options.map((o, i) => (o.disabled ? -1 : i)).filter((i) => i >= 0);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
    if (!forward && !backward) return;
    event.preventDefault();
    const at = enabled.indexOf(index);
    const nextIndex = enabled[(at + (forward ? 1 : -1) + enabled.length) % enabled.length];
    refs.current[nextIndex]?.focus();
    onChange(options[nextIndex].value);
  };

  return (
    <div role="radiogroup" aria-label={label} className={cx(s.group, size === "sm" && s.sm, block && s.block, className)}>
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            disabled={option.disabled}
            className={s.option}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {option.icon ? <Icon name={option.icon} size={size === "sm" ? 13 : 15} /> : null}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
