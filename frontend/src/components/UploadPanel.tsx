import { useRef, useState } from "react";
import { api } from "../api";
import type { AnonymizationMode, DocSummary } from "../types";

const MODES: { value: AnonymizationMode; label: string; hint: string }[] = [
  {
    value: "mapping",
    label: "Eşlemeli",
    hint: "Geri alınabilir. Orijinal ve eşleme tablosu bu makinede kalır; yanlış maskelenen\n      bir terimi tek tıkla geri alabilirsiniz.",
  },
  {
    value: "destructive",
    label: "Geri dönüşsüz",
    hint: "Orijinal ve eşleme tablosu hiç yazılmaz. Kaçan bir veriyi yerinde düzeltemezsiniz;\n      belgeyi yeniden yüklemeniz gerekir.",
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
      <div className="mode-select" role="radiogroup" aria-label="Anonimleştirme modu">
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
        <span>{busy ? "İşleniyor…" : "PDF / DOCX / XLSX yükle"}</span>
      </label>
    </div>
  );
}
