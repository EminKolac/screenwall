import { forwardRef, type ButtonHTMLAttributes } from "react";
import { buttonClass, type ButtonSize, type ButtonVariant } from "./Button";
import { cx } from "./cx";
import { Icon, type IconName } from "./Icon";
import s from "./Button.module.css";

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  icon: IconName;
  /** Accessible name; also shown as a native tooltip. */
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, variant = "quiet", size = "md", className, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      aria-label={label}
      title={label}
      className={buttonClass(variant, size, cx(s.icon, className))}
      {...rest}
    >
      <Icon name={icon} size={size === "sm" ? 15 : 18} />
    </button>
  );
});
