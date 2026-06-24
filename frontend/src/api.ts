import type { ChatMessage, DocDetail, DocSummary, StatusInfo } from "./types";

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
  upload: (file: File): Promise<DocSummary> => {
    const fd = new FormData();
    fd.append("file", file);
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
  chat: (id: string, messages: ChatMessage[]): Promise<{ answer: string }> =>
    fetch(`/api/chat/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    }).then(unwrap),
};
