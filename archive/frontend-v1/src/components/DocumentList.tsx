import type { DocSummary } from "../types";

// Dil bir DURUM değil künye bilgisi — rozet diliyle yazılmamalı. "MIXED" çevrilmemiş
// ve kriptikti; kullanıcı için anlamlı olan hangi dilleri içerdiği.
const LANG_LABEL: Record<string, string> = {
  tr: "TR", en: "EN", mixed: "TR·EN", unknown: "?",
};
import StatusBadge from "./StatusBadge";

export default function DocumentList({
  docs,
  selected,
  onSelect,
  onRefresh,
}: {
  docs: DocSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  const pending = docs.filter((d) => d.status === "needs_human_review").length;
  return (
    <div className="doclist">
      <div className="doclist-head">
        <h3>Belgeler</h3>
        <button className="icon" title="Yenile" onClick={onRefresh}>
          ⟳
        </button>
      </div>
      {docs.length === 0 && <p className="muted">Henüz belge yok.</p>}
      {pending > 0 && (
        <p className="pending-note">
          {pending} belge onayınızı bekliyor.
        </p>
      )}
      {docs.map((d) => (
        <button
          key={d.id}
          className={"docitem" + (d.id === selected ? " active" : "")}
          onClick={() => onSelect(d.id)}
        >
          <div className="docitem-name">{d.filename}</div>
          <div className="docitem-meta">
            <span className="lang">{LANG_LABEL[d.language] ?? d.language.toUpperCase()}</span>
            <StatusBadge status={d.status} label={d.status_label} />
          </div>
        </button>
      ))}
    </div>
  );
}
