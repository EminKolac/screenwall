import { useId, useRef, useState } from "react";
import { reviewReload, useApprove, useReject } from "../../api/queries";
import { tr } from "../../copy/tr";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";
import { DeleteDialog } from "./DeleteDialog";
import { useReview } from "./reviewContext";
import { reviewFailureToast } from "./reviewToast";
import { ShortcutsDialog } from "./ShortcutsDialog";
import s from "./WorkspaceHeader.module.css";

function useFail() {
  const toast = useToast();
  return (error: unknown) => toast.show(reviewFailureToast(error));
}

function ApproveDialog() {
  const { doc, payload, dialog, setDialog } = useReview();
  const approve = useApprove(doc.id);
  const toast = useToast();
  const fail = useFail();
  const confirmRef = useRef<HTMLButtonElement>(null);
  const close = () => setDialog(null);

  const confirm = async () => {
    try {
      // Approve exactly the revision the person has been looking at.
      await approve.mutateAsync(payload.document.revision);
      close();
      toast.show(tr.review.toast.approved);
    } catch (error) {
      // The review was reloaded (changed, or the fresh audit found something): look again first.
      if (reviewReload(error)) close();
      fail(error);
    }
  };

  return (
    <Dialog
      open={dialog === "approve"}
      onClose={close}
      size="sm"
      title={tr.review.approveDialog.title}
      description={approve.isPending ? tr.review.approveDialog.checking : tr.review.approveDialog.body}
      initialFocus={confirmRef}
      footer={
        <>
          <Button variant="quiet" onClick={close}>
            {tr.common.cancel}
          </Button>
          <Button ref={confirmRef} variant="primary" icon="check" loading={approve.isPending} onClick={() => void confirm()}>
            {tr.review.approveDialog.confirm}
          </Button>
        </>
      }
    />
  );
}

function RejectDialog() {
  const { doc, dialog, setDialog } = useReview();
  const reject = useReject(doc.id);
  const toast = useToast();
  const fail = useFail();
  const [reason, setReason] = useState("");
  const fieldId = useId();
  const close = () => setDialog(null);

  const confirm = async () => {
    try {
      await reject.mutateAsync(reason.trim());
      close();
      setReason("");
      toast.show(tr.review.toast.rejected);
    } catch (error) {
      fail(error);
    }
  };

  return (
    <Dialog
      open={dialog === "reject"}
      onClose={close}
      size="sm"
      title={tr.review.rejectDialog.title}
      description={tr.review.rejectDialog.body}
      footer={
        <>
          <Button variant="quiet" onClick={close}>
            {tr.common.cancel}
          </Button>
          <Button variant="danger" loading={reject.isPending} onClick={() => void confirm()}>
            {tr.review.rejectDialog.confirm}
          </Button>
        </>
      }
    >
      <label className={s.field} htmlFor={fieldId}>
        {tr.review.rejectDialog.reasonLabel}
      </label>
      <textarea
        id={fieldId}
        className={s.textarea}
        rows={3}
        maxLength={500}
        value={reason}
        placeholder={tr.review.rejectDialog.reasonPlaceholder}
        onChange={(event) => setReason(event.target.value)}
      />
    </Dialog>
  );
}

/** Every dialog of the review screen, driven by one piece of state in the review context. */
export function ReviewDialogs() {
  const { doc, dialog, setDialog } = useReview();
  return (
    <>
      <ApproveDialog />
      <RejectDialog />
      <DeleteDialog doc={doc} open={dialog === "delete"} onClose={() => setDialog(null)} />
      <ShortcutsDialog open={dialog === "shortcuts"} onClose={() => setDialog(null)} />
    </>
  );
}
