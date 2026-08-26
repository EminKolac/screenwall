import type { AnonymizationMode, ChatMessage, DocDetail, DocSummary, StatusInfo } from "./types";

async function unwrap(r: Response) {
  if (!r.ok) {
    const detail = await r
      .json()
      .then((b) => b.detail)
      .catch(() => r.statusText);
    throw new Error(typeof detail === "string" ? detail : r.statusText);
  }
  return r.json();
}

export const api = {
  statuses: (): Promise<{ statuses: StatusInfo[] }> => fetch("/api/statuses").then(unwrap),
  list: (): Promise<{ documents: DocSummary[] }> => fetch("/api/documents").then(unwrap),
  upload: (file: File, mode?: AnonymizationMode): Promise<DocSummary> => {
    const fd = new FormData();
    fd.append("file", file);
    if (mode) fd.append("mode", mode);
    return fetch("/api/documents", { method: "POST", body: fd }).then(unwrap);
  },
  detail: (id: string): Promise<DocDetail> => fetch(`/api/documents/${id}`).then(unwrap),
  anonymized: (id: string): Promise<string> =>
    fetch(`/api/documents/${id}/anonymized`).then((r) =>
      r.ok ? r.text() : Promise.reject(new Error("no anonymized content")),
    ),
  remove: (id: string) => fetch(`/api/documents/${id}`, { method: "DELETE" }).then(unwrap),
  approve: (id: string) => fetch(`/api/review/${id}/approve`, { method: "POST" }).then(unwrap),
  reject: (id: string) => fetch(`/api/review/${id}/reject`, { method: "POST" }).then(unwrap),
  // Faz 3 — insan düzeltmesi. `unmask` TEK bir yer tutucuyu geri alır; yanıt ham değeri ASLA
  // içermez (bkz. app/api/review.py::unmask), düzeltmenin sonucu yeni anonim metinden görülür.
  unmask: (id: string, token: string): Promise<{ status: string; unmasked_total: number }> =>
    fetch(`/api/review/${id}/unmask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }).then(unwrap),
  // `redact` backend'de vardı ama UI'a hiç bağlı değildi (plan §16.4-C).
  redact: (id: string, terms: string[]): Promise<{ status: string; applied_terms: number }> =>
    fetch(`/api/review/${id}/redact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ terms }),
    }).then(unwrap),
  chat: (id: string, messages: ChatMessage[]): Promise<{ answer: string }> =>
    fetch(`/api/chat/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    }).then(unwrap),
};
