// Mock chat: provider status, preview + consent binding, and answers that cite [S1]/[S2].
import type {
  ChatMessage,
  ChatPreviewRequest,
  ChatPreviewResponse,
  ChatRequest,
  ChatResponse,
  ChatSource,
  ErrorCode,
  ProviderId,
  ProvidersResponse,
} from "../contract";
import { toPayload } from "./store";
import type { MockDoc } from "./types";

export const PROVIDERS: ProvidersResponse = {
  default: "ollama",
  providers: [
    { id: "ollama", label: "Lokal LLM (Ollama)", local: true, available: true, installed: null, compatible: null, authenticated: null, version: "0.12.3", model: "qwen3.5:4b", login_command: null, problem: null },
    { id: "claude_cli", label: "Claude", local: false, available: true, installed: true, compatible: true, authenticated: true, version: "2.1.14", model: null, login_command: "claude auth login", problem: null },
    { id: "codex_cli", label: "ChatGPT (Codex CLI)", local: false, available: false, installed: true, compatible: true, authenticated: false, version: "0.44.0", model: null, login_command: "codex login", problem: "cli_login_required" },
  ],
};

const DESTINATION: Record<ProviderId, string> = {
  ollama: "Bu bilgisayar",
  claude_cli: "Anthropic (Claude)",
  codex_cli: "OpenAI (ChatGPT)",
};

type Outcome<T> = { ok: true; value: T } | { ok: false; error: ErrorCode };

const previews = new Map<string, { provider: ProviderId; docs: string; question: string; history: string }>();

const docsKey = (ids: string[]) => [...ids].sort().join(",");
const historyKey = (history: ChatMessage[] | undefined) =>
  JSON.stringify((history ?? []).map(({ role, content }) => [role, content]));

function fnv(text: string): string {
  let hash = 0x811c9dc5;
  for (const ch of text) {
    hash ^= ch.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

const stems = (text: string) =>
  text
    .toLocaleLowerCase("tr")
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w.length > 2)
    .map((w) => w.slice(0, 5));

function selectSources(docs: MockDoc[], question: string): ChatSource[] {
  const wanted = new Set(stems(question));
  const candidates = docs.flatMap((doc) =>
    toPayload(doc)
      .units.filter((u) => u.kind !== "heading" && u.masked.trim())
      .map((unit) => ({ doc, unit, score: stems(unit.masked).filter((s) => wanted.has(s)).length })),
  );
  const ranked = [...candidates].sort((a, b) => b.score - a.score);
  const picked = ranked[0]?.score ? ranked.filter((c) => c.score > 0).slice(0, 3) : candidates.slice(0, 2);
  return picked.map((c, i) => ({
    id: `S${i + 1}`,
    doc_id: c.doc.id,
    unit_id: c.unit.id,
    label: `${c.doc.filename} · ${c.unit.location}`,
    excerpt: Array.from(c.unit.masked).slice(0, 400).join(""),
  }));
}

function composeText(sources: ChatSource[], question: string, history: ChatMessage[]): string {
  // As in the backend: a source is named by position, never by filename (filenames stay local).
  const docOrder = [...new Set(sources.map((s) => s.doc_id))].sort();
  const blocks = sources
    .map((s, i) => `[${s.id}] document ${docOrder.indexOf(s.doc_id) + 1}, part ${i + 1}\n${s.excerpt}`)
    .join("\n\n");
  const earlier = history.length
    ? `\n\nÖnceki konuşma:\n${history.map((m) => `${m.role === "user" ? "Kullanıcı" : "Yanıt"}: ${m.content}`).join("\n")}`
    : "";
  return `Aşağıdaki kaynaklar maskelenmiş belgelerden alınmıştır. Yalnız bu kaynaklara dayanarak Türkçe yanıt ver ve her bilgiyi [S1] biçiminde kaynağıyla göster.\n\n${blocks}${earlier}\n\nSoru: ${question}`;
}

function checkDocs(docs: Array<MockDoc | undefined>, approved: (d: MockDoc) => boolean): Outcome<MockDoc[]> {
  if (!docs.length || docs.some((d) => !d || !approved(d))) return { ok: false, error: "chat_not_allowed" };
  return { ok: true, value: docs as MockDoc[] };
}

function providerProblem(id: ProviderId): ErrorCode | null {
  const provider = PROVIDERS.providers.find((p) => p.id === id);
  if (!provider) return "provider_unavailable";
  return provider.available ? null : ((provider.problem as ErrorCode | null) ?? "provider_unavailable");
}

export function preview(
  request: ChatPreviewRequest,
  docs: Array<MockDoc | undefined>,
  approved: (d: MockDoc) => boolean,
): Outcome<ChatPreviewResponse> {
  const checked = checkDocs(docs, approved);
  if (!checked.ok) return checked;
  const problem = providerProblem(request.provider);
  if (problem) return { ok: false, error: problem };
  const sources = selectSources(checked.value, request.question);
  const history = request.history ?? [];
  const sent_text = composeText(sources, request.question, history);
  // Like the server: the hash binds provider, sorted document ids and the exact text, history included.
  const preview_hash = fnv(`${request.provider}\n${docsKey(request.doc_ids)}\n${sent_text}`);
  previews.set(preview_hash, {
    provider: request.provider,
    docs: docsKey(request.doc_ids),
    question: request.question,
    history: historyKey(history),
  });
  return {
    ok: true,
    value: {
      provider: request.provider,
      preview_hash,
      destination: DESTINATION[request.provider],
      sources,
      sent_text,
      context_chars: Array.from(sent_text).length,
    },
  };
}

const sentence = (text: string) => {
  const trimmed = text.trim();
  const match = /^(.{12,220}?[.!?])(\s|$)/u.exec(trimmed);
  return (match ? match[1] : trimmed.slice(0, 180)).replace(/[.!?]$/u, "");
};

export function answer(
  request: ChatRequest,
  docs: Array<MockDoc | undefined>,
  approved: (d: MockDoc) => boolean,
): Outcome<ChatResponse> {
  const checked = checkDocs(docs, approved);
  if (!checked.ok) return checked;
  const problem = providerProblem(request.provider);
  if (problem) return { ok: false, error: problem };
  if (request.provider !== "ollama") {
    if (!request.preview_hash) return { ok: false, error: "preview_required" };
    const stored = previews.get(request.preview_hash);
    const same =
      stored &&
      stored.provider === request.provider &&
      stored.question === request.question &&
      stored.docs === docsKey(request.doc_ids) &&
      stored.history === historyKey(request.history);
    if (!same) return { ok: false, error: "preview_mismatch" };
  }
  const sources = selectSources(checked.value, request.question);
  const [first, second] = sources;
  const parts = [`Belgeye göre “${sentence(first.excerpt)}” [S1].`];
  if (second) parts.push(`İlgili bir başka bölümde “${sentence(second.excerpt)}” ifadesi geçiyor [S2].`);
  parts.push("Kişisel bilgiler maskeli olduğu için yanıtta yer tutucu olarak görünür.");
  return {
    ok: true,
    value: {
      answer: parts.join(" "),
      citations: second ? [first, second] : [first],
      provider: request.provider,
      elapsed_ms: request.provider === "ollama" ? 1640 : 2380,
    },
  };
}
