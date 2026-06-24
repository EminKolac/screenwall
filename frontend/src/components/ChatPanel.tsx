import { useState } from "react";
import { api } from "../api";
import type { ChatMessage } from "../types";

export default function ChatPanel({ id }: { id: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

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
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card chat">
      <h3>💬 Chat — anonymized content only</h3>
      <div className="messages">
        {messages.length === 0 && <p className="muted">Ask a question about the anonymized document.</p>}
        {messages.map((m, i) => (
          <div key={i} className={"msg " + m.role}>
            {m.content}
          </div>
        ))}
        {busy && <div className="msg assistant">…</div>}
      </div>
      {err && <div className="error">{err}</div>}
      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="e.g. What are the key obligations?"
          disabled={busy}
        />
        <button onClick={send} disabled={busy}>
          Send
        </button>
      </div>
    </div>
  );
}
