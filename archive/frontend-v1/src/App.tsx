import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import DocumentDetail from "./components/DocumentDetail";
import DocumentList from "./components/DocumentList";
import UploadPanel from "./components/UploadPanel";
import type { DocSummary, StatusInfo } from "./types";

export default function App() {
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [statuses, setStatuses] = useState<StatusInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      setDocs((await api.list()).documents);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    api.statuses().then((r) => setStatuses(r.statuses)).catch(() => {});
    refresh();
  }, [refresh]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <h1>Screenwall</h1>
          <p>Belgeni ver, verini verme — her şey bu makinede</p>
        </div>
      </header>
      <div className="layout">
        <aside className="sidebar">
          <UploadPanel
            onUploaded={(d) => {
              refresh();
              setSelected(d.id);
            }}
            onError={setError}
          />
          <DocumentList docs={docs} selected={selected} onSelect={setSelected} onRefresh={refresh} />
        </aside>
        <main className="main">
          {error && (
            <div className="error" onClick={() => setError("")}>
              {error} <span className="dismiss">✕</span>
            </div>
          )}
          {selected ? (
            <DocumentDetail
              key={selected}
              id={selected}
              statuses={statuses}
              onChanged={refresh}
              onDeleted={() => {
                setSelected(null);
                refresh();
              }}
            />
          ) : (
            <div className="empty">
              <h2>Bir belge seçin ya da yükleyin</h2>
              <p>PDF, Word veya Excel. Türkçe, İngilizce ya da karışık. Dosyanın kendisi
              hiçbir zaman bu bilgisayardan çıkmıyor.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
