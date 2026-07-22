import { useEffect, useState } from "react";
import { api } from "../api";
import type { DocDetail, StatusInfo } from "../types";
import ChatPanel from "./ChatPanel";
import StatusBadge from "./StatusBadge";
import StatusFlow from "./StatusFlow";

export default function DocumentDetail({
  id,
  statuses,
  onChanged,
  onDeleted,
}: {
  id: string;
  statuses: StatusInfo[];
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [anon, setAnon] = useState("");
  const [err, setErr] = useState("");

  const load = () => {
    api.detail(id).then(setDoc).catch((e) => setErr(e.message));
    api.anonymized(id).then(setAnon).catch(() => setAnon(""));
  };
  useEffect(load, [id]);

  if (!doc) return <div className="empty">Loading…</div>;

  const approved = doc.status === "approved";
  const needsReview = doc.status === "needs_human_review";
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      load();
      onChanged();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <h2>{doc.filename}</h2>
          <div className="sub">
            {doc.kind.toUpperCase()} · {doc.language.toUpperCase()} · {doc.iterations.length} iteration(s)
          </div>
        </div>
        <div className="actions">
          {needsReview && (
            <>
              <button className="ok" onClick={() => act(() => api.approve(id))}>
                Approve
              </button>
              <button onClick={() => act(() => api.reject(id))}>Reject</button>
            </>
          )}
          {anon && (
            <a className="btn" href={`/api/documents/${id}/download`} rel="noreferrer">
              ⬇ Download (PDF)
            </a>
          )}
          <button className="danger" onClick={() => act(async () => { await api.remove(id); onDeleted(); })}>
            Delete
          </button>
        </div>
      </div>

      {err && <div className="error">{err}</div>}
      <StatusFlow statuses={statuses} current={doc.status} />

      <div className="cols">
        <section className="card">
          <h3>Iteration history &amp; findings</h3>
          {doc.iterations.length === 0 && (
            <p className="muted">No anonymization iterations (routed directly to human review).</p>
          )}
          {doc.iterations.map((it) => (
            <div key={it.iteration} className="iter">
              <div className="iter-head">
                <b>Tur {it.iteration}</b>
                <span className="muted">{it.presidio_entities} maskelenen</span>
                {it.audit && (
                  <StatusBadge
                    status={it.audit.approved ? "approved" : "needs_human_review"}
                    label={it.audit.approved ? "Denetim OK" : `Flagged (${it.audit.risk_level})`}
                  />
                )}
              </div>
              <div className="chips stages">
                <span className="chip">① Presidio {it.by_source?.presidio ?? it.presidio_entities}</span>
                <span className="chip">② Privacy Filter {it.by_source?.privacy_filter ?? "kapalı"}</span>
                {it.by_source?.deny != null && <span className="chip">deny {it.by_source.deny}</span>}
                <span className="chip">
                  ③ Denetim {it.audit ? (it.audit.approved ? "temiz" : it.audit.risk_level) : "—"}
                </span>
              </div>
              {it.audit && (
                <div className="iter-body">
                  <div className="muted">{it.audit.summary}</div>
                  {it.audit.remaining_sensitive_items.length > 0 && (
                    <ul className="findings">
                      {it.audit.remaining_sensitive_items.map((f, i) => (
                        <li key={i}>
                          <span className="ftype">{f.type}</span> {f.snippet}{" "}
                          {f.location && <em>{f.location}</em>}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="chips">
                    {Object.entries(it.placeholders_used).map(([k, v]) => (
                      <span key={k} className="chip">
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </section>

        <section className="card">
          <h3>
            Anonymized preview {approved && <span className="badge ok">Approved</span>}
          </h3>
          <pre className="anon">{anon || "(not available)"}</pre>
        </section>
      </div>

      {doc.chat_ready ? (
        <ChatPanel id={id} />
      ) : (
        <div className="card locked">🔒 Chat is locked until the document is approved.</div>
      )}
    </div>
  );
}
