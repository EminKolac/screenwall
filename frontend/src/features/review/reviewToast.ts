import { ApiError } from "../../api/client";
import { reviewReload, type ReviewReload } from "../../api/queries";
import { errorMessage, errorText, tr } from "../../copy/tr";
import type { ToastInput } from "../../ui/Toast";

/** By the time these show, the review hooks have already put the current review on screen. */
const RELOADED: Record<ReviewReload, string> = {
  stale_revision: tr.review.toast.staleReloaded,
  audit_not_clean: tr.review.toast.auditNotClean,
  unresolved_items: errorText.unresolved_items,
};

/** The toast after a failed review action: a calm note when the review was reloaded, else the error. */
export function reviewFailureToast(error: unknown): ToastInput {
  const reload = reviewReload(error);
  if (reload) return { message: RELOADED[reload], tone: "info" };
  return { message: errorMessage(error instanceof ApiError ? error.code : "unknown_error"), tone: "error" };
}
