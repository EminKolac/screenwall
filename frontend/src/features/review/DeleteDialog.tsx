import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { DocumentSummary } from "../../api/contract";
import { ApiError } from "../../api/client";
import { isProcessing, useDeleteDocument } from "../../api/queries";
import { errorMessage, errorText, tr } from "../../copy/tr";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";

interface DeleteDialogProps {
  doc: DocumentSummary;
  open: boolean;
  onClose: () => void;
}

/** Removes the document from this computer after an explicit confirmation. */
export function DeleteDialog({ doc, open, onClose }: DeleteDialogProps) {
  const remove = useDeleteDocument();
  const toast = useToast();
  const navigate = useNavigate();
  const cancel = useRef<HTMLButtonElement>(null);
  // Last guard behind every entry point: no delete until the document settles. Deliberately stricter
  // than the backend, which refuses (409 document_busy) only while extracting/masking/auditing.
  const busy = isProcessing(doc.status);

  const confirm = async () => {
    if (busy) return;
    try {
      await remove.mutateAsync(doc.id);
      onClose();
      toast.show(tr.review.toast.deleted);
      navigate("/");
    } catch (error) {
      toast.show({ message: errorMessage(error instanceof ApiError ? error.code : "unknown_error"), tone: "error" });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="sm"
      title={tr.review.deleteDialog.title}
      initialFocus={cancel}
      description={busy ? errorText.document_busy : tr.review.deleteDialog.body(doc.filename)}
      footer={
        <>
          <Button ref={cancel} variant="quiet" onClick={onClose}>
            {tr.common.cancel}
          </Button>
          <Button variant="danger" icon="trash" disabled={busy} loading={remove.isPending} onClick={() => void confirm()}>
            {tr.review.deleteDialog.confirm}
          </Button>
        </>
      }
    />
  );
}
