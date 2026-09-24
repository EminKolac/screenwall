import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMessage } from "../types";

/* Yanıt YEREL bir modelden geliyor ve 20-60 saniye sürebiliyor. Önceki sürümde tek geri bildirim
   küçük bir "…" idi; kullanıcı bunu "sohbet çalışmıyor" diye okuyordu. Artık geçen süre sayılıyor,
   ne olduğu yazıyor ve giriş alanı kilitleniyor. */
export default function ChatPanel({ id }: { id: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [secs, setSecs] = useState(0);
  const [err, setErr] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!busy) return;
    setSecs(0);
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [messages, busy]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setErr("");
    try {
      const r = await api.chat(id, next);
      setMessages([...next, { role: "assistant", content: r.answer }]);
    } catch (e: any) {
      setErr(e.message || "Yanıt alınamadı.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card chat">
      <h3>Soru sor — yalnız anonim metin üzerinden</h3>
      <p className="muted">
        Sorularınız yerel bir modele gidiyor ve model yalnız maskelenmiş kopyayı görüyor.
        Orijinal belge hiçbir zaman gönderilmiyor.
      </p>
      <div className="messages">
        {messages.length === 0 && !busy && (
          <div className="chat-empty">
            <p className="muted">Örnek sorular:</p>
            <div className="chips">
              {["Bu belge ne hakkında?", "Önemli tarihler neler?", "Hangi tutarlar geçiyor?"].map(
                (q) => (
                  <button key={q} className="chip chip-action" onClick={() => setInput(q)}>
                    {q}
                  </button>
                ),
              )}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={"msg " + m.role}>
            {m.content}
          </div>
        ))}
        {busy && (
          <div className="msg assistant thinking">
            Yanıt hazırlanıyor… <b>{secs} sn</b>
            <div className="thinking-note">
              Yerel model, ilk soruda 20-60 saniye sürebilir. Sekmeyi kapatmayın.
            </div>
          </div>
        )}
        <div ref={end} />
      </div>
      {err && <div className="error">{err}</div>}
      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={busy ? "Yanıt bekleniyor…" : "Belge hakkında bir soru yazın"}
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          {busy ? "…" : "Gönder"}
        </button>
      </div>
    </div>
  );
}
