import { useState } from "react";
import type { DocumentSummary } from "../../api/contract";
import { api, ApiError } from "../../api/client";
import { errorMessage } from "../../copy/tr";
import { useToast } from "../../ui/Toast";

function fallbackName(filename: string): string {
  const stem = filename.replace(/\.[^.]+$/, "");
  return `${stem}-maskeli.pdf`;
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** GET /download through the API client, so failures surface as sentences instead of a blank tab. */
export function useDownload(doc: DocumentSummary) {
  const toast = useToast();
  const [pending, setPending] = useState(false);
  const start = async () => {
    setPending(true);
    try {
      const { blob, filename } = await api.download(doc.id);
      save(blob, filename ?? fallbackName(doc.filename));
    } catch (error) {
      toast.show({ message: errorMessage(error instanceof ApiError ? error.code : "unknown_error"), tone: "error" });
    } finally {
      setPending(false);
    }
  };
  return { pending, start };
}
