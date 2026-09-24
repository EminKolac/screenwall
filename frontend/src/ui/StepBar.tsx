import type { DocStatus, ReviewReason } from "../api/contract";
import { tr } from "../copy/tr";
import { cx } from "./cx";
import { Icon } from "./Icon";
import s from "./StepBar.module.css";

export type StepState = "done" | "current" | "upcoming" | "failed" | "rejected";

const STEP_COUNT = 5;
const CURRENT: Partial<Record<DocStatus, number>> = { queued: 1, extracting: 1, masking: 2, auditing: 3, needs_review: 4 };

/** Which pipeline step failed, read from the machine reason codes (defaults to extraction). */
function failedStep(reasons: ReviewReason[]): number {
  const codes = reasons.map((r) => r.code).join(" ");
  if (/audit/.test(codes)) return 3;
  if (/mask/.test(codes)) return 2;
  return 1;
}

/** Pure mapping from a document status to the five step states. */
export function stepStates(status: DocStatus, reasons: ReviewReason[] = []): StepState[] {
  const steps = Array.from({ length: STEP_COUNT }, (_, i) => i);
  if (status === "approved") return steps.map(() => "done");
  if (status === "rejected") return steps.map((i) => (i < STEP_COUNT - 1 ? "done" : "rejected"));
  if (status === "failed") {
    const at = failedStep(reasons);
    return steps.map((i) => (i < at ? "done" : i === at ? "failed" : "upcoming"));
  }
  const current = CURRENT[status] ?? 0;
  return steps.map((i) => (i < current ? "done" : i === current ? "current" : "upcoming"));
}

const MARKER = { done: "check", failed: "x", rejected: "x" } as const;

interface StepBarProps {
  status: DocStatus;
  reasons?: ReviewReason[];
  centered?: boolean;
  className?: string;
}

export function StepBar({ status, reasons = [], centered = false, className }: StepBarProps) {
  const states = stepStates(status, reasons);
  const review = status === "needs_review";
  return (
    <div className={cx(s.wrap, className)}>
      <ol className={cx(s.steps, review && s.review, centered && s.centered)} aria-label={tr.steps.label} data-status={status}>
        {tr.steps.names.map((name, i) => {
          const state = states[i];
          const icon = state === "done" || state === "failed" || state === "rejected" ? MARKER[state] : null;
          return (
            <li key={name} className={s.step} data-state={state} aria-current={state === "current" ? "step" : undefined}>
              <span className={s.marker} aria-hidden="true">
                {icon ? <Icon name={icon} size={11} /> : null}
              </span>
              <span className={s.name}>{name}</span>
              <span className="sr-only">{`, ${tr.steps.state[state]}`}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
