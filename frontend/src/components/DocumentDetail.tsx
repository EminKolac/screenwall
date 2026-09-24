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
  const [busyToken, setBusyToken] = useState("");
  // Hangi tür grupları açık. Gerçek bir belgede 150+ yer tutucu çıkabiliyor
  // (ölçüldü: bir telekonferans metninde 94 PERSON + 58 LOCATION); hepsini düz bir
  // çip duvarı olarak basmak listeyi taranamaz yapıyor ve önizlemeyi ekrandan itiyor.
  const [openTypes, setOpenTypes] = useState<Set<string>>(new Set());
  // Onay artık LLM yeniden denetimi yapıyor (~16 sn). Kilitlenmezse çift tık iki
  // IterationRecord yazıyor ve kullanıcı bu sırada indirmeye basıp 403 alıyordu.
  const [deciding, setDeciding] = useState(false);

  const load = () => {
    api.detail(id).then(setDoc).catch((e) => setErr(e.message));
    api.anonymized(id).then(setAnon).catch(() => setAnon(""));
  };
  useEffect(load, [id]);

  if (!doc) return <div className="empty">Yükleniyor…</div>;

  const approved = doc.status === "approved";
  const needsReview = doc.status === "needs_human_review";
  // Anonim metinde GERÇEKTEN geçen yer tutucular. Iterasyon sayaçlarından türetmek yanlış olurdu:
  // sayaçlar kümülatif (her turda yeniden sayılır) ve geri alınmış bir token'ı da sayardı.
  const maskedTokens = Array.from(new Set(anon.match(/<[A-Z]+_\d+>/g) ?? [])).sort();
  const byType = new Map<string, string[]>();
  for (const t of maskedTokens) {
    const type = t.slice(1, t.lastIndexOf("_"));
    byType.set(type, [...(byType.get(type) ?? []), t]);
  }
  const groups = [...byType.entries()].sort((a, b) => b[1].length - a[1].length);
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
            {doc.kind.toUpperCase()} · {doc.language.toUpperCase()} · {doc.iterations.length} tur
            {" · "}
            <span title={doc.mode === "destructive"
              ? "Geri dönüşsüz — orijinal ve eşleme hiç yazılmadı"
              : "Geri alınabilir — orijinal ve eşleme bu makinede"}>
              {doc.mode === "destructive" ? "geri dönüşsüz" : "eşlemeli"}
            </span>
          </div>
        </div>
        <div className="actions">
          {needsReview && (
            <>
              <button
                className="ok"
                disabled={deciding}
                onClick={() =>
                  act(async () => {
                    setDeciding(true);
                    try {
                      await api.approve(id);
                    } finally {
                      setDeciding(false);
                    }
                  })
                }
              >
                {deciding ? "Denetleniyor…" : "Onayla"}
              </button>
              <button
                disabled={deciding}
                onClick={() =>
                  act(async () => {
                    setDeciding(true);
                    try {
                      await api.reject(id);
                    } finally {
                      setDeciding(false);
                    }
                  })
                }
              >
                Reddet
              </button>
            </>
          )}
          {/* Yalnız ONAYDAN sonra. Daha önce `anon` doluluğuna bakıyordu; önizleme incelemeye
              açılınca düğme çalışmayacağı yerde belirip 403 veriyordu. */}
          {approved && anon && (
            <a className="btn" href={`/api/documents/${id}/download`} rel="noreferrer">
              ⬇ PDF indir
            </a>
          )}
          {!approved && anon && (
            <span className="btn disabled" title="İndirme onaydan sonra açılır">
              ⬇ PDF indir
            </span>
          )}
          <button className="danger" onClick={() => act(async () => { await api.remove(id); onDeleted(); })}>
            Sil
          </button>
        </div>
      </div>

      {err && <div className="error">{err}</div>}
      <StatusFlow statuses={statuses} current={doc.status} />

      {/* Gerekçe daha önce çıkarma aşamasında hesaplanıp atılıyordu: kullanıcı 'Denetim OK'
          ile 'Needs Human Review' etiketlerini yan yana görüp neden beklediğini anlayamıyordu. */}
      {/* Onaylı belgede kullanıcı sonraki adımı bilmiyordu: ekranda yalnız teşhis verisi vardı
          (Presidio sayısı, tur geçmişi, 151 yer tutucu). Karar ve eylem artık en üstte. */}
      {approved && (
        <div className="next-note">
          <b>Bu belge hazır. Şimdi ne yapabilirsiniz?</b>
          <ol>
            <li>
              <b>PDF indirin</b> — maskelenmiş kopya, orijinalden değil onaylı metinden yeniden
              basılır.
            </li>
            <li>
              <b>Soru sorun</b> — aşağıdaki sohbet yalnız anonim metni görür.
            </li>
            <li>
              <b>Yanlış maskelenmiş bir terim varsa geri alın</b> — aşağıdaki listeden tıklayın;
              belge yeniden anonimleştirilip tekrar onayınıza düşer.
            </li>
          </ol>
        </div>
      )}

      {needsReview && (
        <div className="review-note">
          <b>Bu belge neden onayınızı bekliyor?</b>
          {doc.review_reason && doc.review_reason.length > 0 ? (
            <ul>
              {doc.review_reason.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">Denetim kalıntı bulduğu için — ayrıntı aşağıdaki tur geçmişinde.</p>
          )}
          <p className="muted">
            Aşağıdaki anonim önizlemeyi okuyup Onayla ya da Reddet ile karar verin.
          </p>
        </div>
      )}

      {/* Faz 3 — insan düzeltmesi. Bugüne kadar UI yalnız "PERSON: 4" gibi AGREGAT sayı
          gösteriyordu; yanlış maskelenmiş tek bir terimi geri almanın hiçbir yolu yoktu. */}
      {maskedTokens.length > 0 && (
        <section className="card">
          <h3>
            Yanlış maskelenmiş bir şey var mı?
            <span className="badge info">{maskedTokens.length}</span>
          </h3>
          <p className="muted">
            Bir türe tıklayıp içindekilere bakın. Kişi ya da yer OLMAYAN bir şey
            maskelenmişse üzerine tıklayarak geri alın — terim bu belgenin izin listesine
            eklenir, belge yeniden anonimleştirilir ve tekrar onayınıza düşer. Ham değer
            hiçbir zaman API yanıtında dönmez.
          </p>
          <div className="groups">
            {groups.map(([type, tokens]) => {
              const open = openTypes.has(type);
              return (
                <div key={type} className="group">
                  <button
                    className="group-head"
                    aria-expanded={open}
                    onClick={() =>
                      setOpenTypes((prev) => {
                        const next = new Set(prev);
                        next.has(type) ? next.delete(type) : next.add(type);
                        return next;
                      })
                    }
                  >
                    <span className="caret">{open ? "▾" : "▸"}</span>
                    <span className="group-name">{type}</span>
                    <span className="group-count">{tokens.length}</span>
                  </button>
                  {open && (
                    <div className="chips">
                      {tokens.map((t) => (
                        <button
                          key={t}
                          className="chip chip-action"
                          disabled={busyToken !== "" || doc.mode === "destructive"}
                          title={
                            doc.mode === "destructive"
                              ? "Destructive modda geri alma mümkün değil (eşleme hiç saklanmadı)"
                              : `${t} maskesini kaldır`
                          }
                          onClick={() =>
                            act(async () => {
                              setBusyToken(t);
                              try {
                                await api.unmask(id, t);
                              } finally {
                                setBusyToken("");
                              }
                            })
                          }
                        >
                          {busyToken === t ? "…" : `${t} ✕`}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <div className="cols">
        <details className="card tech">
          <summary>Teknik ayrıntı — tur geçmişi ve bulgular</summary>
          {doc.iterations.length === 0 && (
            <p className="muted">Hiç anonimleştirme turu çalışmadı — belge doğrudan insan incelemesine yönlendirildi.</p>
          )}
          {doc.iterations.map((it) => (
            <div key={it.iteration} className="iter">
              <div className="iter-head">
                <b>Tur {it.iteration}</b>
                <span className="muted">{it.presidio_entities} maskelenen</span>
                {it.audit && (
                  <StatusBadge
                    status={it.audit.approved ? "approved" : "needs_human_review"}
                    label={it.audit.approved ? "Denetim temiz" : `Kalıntı var (${it.audit.risk_level})`}
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
        </details>

        <section className="card">
          <h3>
            Anonim önizleme{" "}
            {approved ? (
              <span className="badge ok">Onaylandı</span>
            ) : needsReview ? (
              <span className="badge warn">İnceleniyor</span>
            ) : null}
          </h3>
          <pre className="anon">
            {anon || "Önizleme yalnız incelemedeki ya da onaylanmış belgelerde görünür."}
          </pre>
        </section>
      </div>

      {doc.chat_ready ? (
        <ChatPanel id={id} />
      ) : (
        <div className="card locked">Sohbet, belge onaylanana kadar kapalı.</div>
      )}
    </div>
  );
}
