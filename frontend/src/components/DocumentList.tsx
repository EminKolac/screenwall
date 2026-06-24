import type { DocSummary } from "../types";
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
  return (
    <div className="doclist">
      <div className="doclist-head">
        <h3>Documents</h3>
        <button className="icon" title="Refresh" onClick={onRefresh}>
          ⟳
        </button>
      </div>
      {docs.length === 0 && <p className="muted">No documents yet.</p>}
      {docs.map((d) => (
        <button
          key={d.id}
          className={"docitem" + (d.id === selected ? " active" : "")}
          onClick={() => onSelect(d.id)}
        >
          <div className="docitem-name">{d.filename}</div>
          <div className="docitem-meta">
            <span className="lang">{d.language.toUpperCase()}</span>
            <StatusBadge status={d.status} label={d.status_label} />
          </div>
        </button>
      ))}
    </div>
  );
}
