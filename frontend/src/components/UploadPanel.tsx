import { useRef, useState } from "react";
import { api } from "../api";
import type { DocSummary } from "../types";

export default function UploadPanel({
  onUploaded,
  onError,
}: {
  onUploaded: (d: DocSummary) => void;
  onError: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const handle = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    onError("");
    try {
      onUploaded(await api.upload(file));
    } catch (e: any) {
      onError(e.message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="upload">
      <label className={"dropzone" + (busy ? " busy" : "")}>
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,.xlsx"
          disabled={busy}
          onChange={(e) => handle(e.target.files?.[0])}
        />
        <span>{busy ? "Processing…" : "⬆  Upload PDF / DOCX / XLSX"}</span>
      </label>
    </div>
  );
}
