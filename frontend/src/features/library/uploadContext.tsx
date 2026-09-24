import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { DocumentSummary, Mode } from "../../api/contract";
import { ApiError } from "../../api/client";
import { isProcessing, useDocuments, useSettings, useUpload } from "../../api/queries";
import { errorMessage, tr } from "../../copy/tr";
import { useToast } from "../../ui/Toast";
import { docPath } from "../../app/paths";
import { ACCEPT_ATTR, ACCEPTED_FILE } from "./filters";

export interface UploadEntry {
  key: string;
  name: string;
  phase: "sending" | "accepted" | "failed" | "done";
  docId?: string;
  error?: string;
}

interface UploadApi {
  mode: Mode;
  setMode: (mode: Mode) => void;
  pick: () => void;
  enqueue: (files: FileList | File[]) => void;
  entries: UploadEntry[];
  dismiss: (key: string) => void;
}

const UploadContext = createContext<UploadApi | null>(null);
let seq = 0;

export function UploadProvider({ children }: { children: ReactNode }) {
  const settings = useSettings();
  const docs = useDocuments();
  const upload = useUpload();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [chosenMode, setMode] = useState<Mode | null>(null);
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const where = useRef({ path: location.pathname, docs: docs.data });
  where.current = { path: location.pathname, docs: docs.data };

  const mode: Mode = chosenMode ?? settings.data?.default_mode ?? "mapping";

  const patch = useCallback((key: string, next: Partial<UploadEntry>) => {
    setEntries((prev) => prev.map((e) => (e.key === key ? { ...e, ...next } : e)));
  }, []);

  const dismiss = useCallback((key: string) => {
    setEntries((prev) => prev.filter((e) => e.key !== key));
  }, []);

  /** Open the new document right away unless the person is busy reviewing something else. */
  const mayOpen = useCallback(() => {
    const { path, docs: list } = where.current;
    if (path === "/") return true;
    const current = list?.find((d) => path.startsWith(docPath(d.id)));
    return !current || !current.can.review;
  }, []);

  const enqueue = useCallback(
    (files: FileList | File[]) => {
      let first = true;
      for (const file of Array.from(files)) {
        const key = `u${++seq}`;
        if (!ACCEPTED_FILE.test(file.name)) {
          setEntries((prev) => [...prev, { key, name: file.name, phase: "failed", error: errorMessage("unsupported_file_type") }]);
          continue;
        }
        setEntries((prev) => [...prev, { key, name: file.name, phase: "sending" }]);
        const openAfter = first;
        first = false;
        chain.current = chain.current.then(async () => {
          try {
            const summary: DocumentSummary = await upload.mutateAsync({ file, mode });
            patch(key, { phase: "accepted", docId: summary.id });
            if (openAfter && mayOpen()) navigate(docPath(summary.id));
          } catch (error) {
            const code = error instanceof ApiError ? error.code : "unknown_error";
            patch(key, { phase: "failed", error: errorMessage(code) });
          }
        });
      }
    },
    [mode, upload, patch, mayOpen, navigate],
  );

  // Retire finished uploads; offer to open ones that finished while the person was elsewhere.
  useEffect(() => {
    for (const entry of entries) {
      if (entry.phase !== "accepted" || !entry.docId) continue;
      const doc = docs.data?.find((d) => d.id === entry.docId);
      if (!doc || isProcessing(doc.status)) continue;
      patch(entry.key, { phase: "done" });
      window.setTimeout(() => dismiss(entry.key), 1800);
      const ready = doc.status === "needs_review" || doc.status === "approved";
      const viewing = location.pathname.startsWith(docPath(doc.id));
      if (!ready || viewing) continue;
      if (location.pathname === "/") navigate(docPath(doc.id));
      else
        toast.show({
          message: tr.upload.readyToast(doc.filename),
          tone: "info",
          action: { label: tr.upload.open, onClick: () => navigate(docPath(doc.id)) },
        });
    }
  }, [docs.data, entries, location.pathname, navigate, patch, dismiss, toast]);

  const pick = useCallback(() => input.current?.click(), []);

  const api = useMemo(() => ({ mode, setMode, pick, enqueue, entries, dismiss }), [mode, pick, enqueue, entries, dismiss]);

  return (
    <UploadContext.Provider value={api}>
      {children}
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT_ATTR}
        aria-label={tr.upload.inputLabel}
        data-testid="upload-input"
        onChange={(event) => {
          if (event.target.files?.length) enqueue(event.target.files);
          event.target.value = "";
        }}
      />
    </UploadContext.Provider>
  );
}

export function useUploads(): UploadApi {
  const ctx = useContext(UploadContext);
  if (!ctx) throw new Error("useUploads needs <UploadProvider>");
  return ctx;
}
