import { useRef, useState } from "react";
import { api } from "../api";
import type { AnonymizationMode, DocSummary } from "../types";

const MODES: { value: AnonymizationMode; label: string; hint: string }[] = [
  {
    value: "mapping",
    label: "Mapping",
    hint: "Reversible — original + mapping kept locally so a reviewer can compare and correct.",
  },
  {
    value: "destructive",
    label: "Destructive",
    hint: "Irreversible — original and mapping are never written. A missed entity can't be " +
      "corrected in place; re-upload to try again.",
  },
];

export default function UploadPanel({
  onUploaded,
  onError,
}: {
  onUploaded: (d: DocSummary) => void;
  onError: (m: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<AnonymizationMode>("mapping");
  const input = useRef<HTMLInputElement>(null);

  const handle = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    onError("");
    try {
      onUploaded(await api.upload(file, mode));
    } catch (e: any) {
      onError(e.message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="upload">
      <div className="mode-select" role="radiogroup" aria-label="Anonymization mode">
        {MODES.map((m) => (
          <button
            key={m.value}
            type="button"
            className={"mode-option" + (mode === m.value ? " active" : "")}
            role="radio"
            aria-checked={mode === m.value}
            title={m.hint}
            disabled={busy}
            onClick={() => setMode(m.value)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="mode-hint">{MODES.find((m) => m.value === mode)!.hint}</p>
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
