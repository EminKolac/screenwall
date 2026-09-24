import { forwardRef, type ButtonHTMLAttributes, type MouseEvent } from "react";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import s from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "accent" | "quiet" | "danger" | "link";
export type ButtonSize = "sm" | "md";

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string) {
  return cx(s.btn, variant !== "secondary" && s[variant], size === "sm" && s.sm, extra);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: IconName;
  iconEnd?: IconName;
  /** Shows a spinner and ignores clicks while keeping focus on the button. */
  loading?: boolean;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, iconEnd, loading, block, className, children, onClick, type, ...rest },
  ref,
) {
  const iconSize = size === "sm" ? 14 : 16;
  const handleClick = (event: MouseEvent<HTMLButtonElement>) => {
    if (loading) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  };
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonClass(variant, size, cx(block && s.block, loading && s.busy, className))}
      aria-busy={loading || undefined}
      onClick={handleClick}
      {...rest}
    >
      {loading ? <span className={s.spinner} aria-hidden="true" /> : icon ? <Icon name={icon} size={iconSize} /> : null}
      {children !== undefined && children !== null ? <span className={s.label}>{children}</span> : null}
      {iconEnd ? <Icon name={iconEnd} size={iconSize} /> : null}
    </button>
  );
});
