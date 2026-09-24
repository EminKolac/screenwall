// Thin fetch wrapper around the fixed contract: session + CSRF, one retry on an expired session,
// and every failure normalised into ApiError{code,status}.
import type {
  AppSettings,
  ApproveRequest,
  ChatPreviewRequest,
  ChatPreviewResponse,
  ChatRequest,
  ChatResponse,
  DecisionRequest,
  DocumentList,
  DocumentSummary,
  HealthResponse,
  Mode,
  PageMarks,
  ProvidersResponse,
  RejectRequest,
  ReviewPayload,
  SessionResponse,
} from "./contract";
import { isErrorCode, type AnyErrorCode } from "../copy/tr";

export class ApiError extends Error {
  readonly code: AnyErrorCode;
  readonly status: number;

  constructor(code: AnyErrorCode, status: number) {
    super(code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export type Transport = (input: string, init: RequestInit) => Promise<Response>;

const defaultTransport: Transport = (input, init) => globalThis.fetch(input, init);
let transport: Transport = defaultTransport;
let pageImageResolver: ((docId: string, page: number) => string) | null = null;
let csrfPromise: Promise<string> | null = null;

/** Swap the network layer (the in-browser mock uses this). Passing null restores fetch. */
export function setTransport(next: Transport | null): void {
  transport = next ?? defaultTransport;
  resetSession();
}

export function setPageImageResolver(next: ((docId: string, page: number) => string) | null): void {
  pageImageResolver = next;
}

export function resetSession(): void {
  csrfPromise = null;
}

async function readError(res: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await res.json()) as { detail?: unknown })?.detail;
  } catch {
    detail = undefined;
  }
  if (typeof detail === "string" && isErrorCode(detail)) return new ApiError(detail, res.status);
  return new ApiError(res.status >= 500 ? "internal_error" : "unknown_error", res.status);
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await transport(path, { credentials: "same-origin", ...init });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network_error", 0);
  }
}

/** GET /api/session once; it sets the HttpOnly session cookie and hands out the CSRF token. */
function csrfToken(): Promise<string> {
  if (!csrfPromise) {
    const pending = (async () => {
      const res = await send("/api/session", { method: "GET", headers: { Accept: "application/json" } });
      if (!res.ok) throw await readError(res);
      return ((await res.json()) as SessionResponse).csrf_token;
    })();
    pending.catch(() => {
      if (csrfPromise === pending) csrfPromise = null;
    });
    csrfPromise = pending;
  }
  return csrfPromise;
}

const MUTATING = new Set(["POST", "PUT", "DELETE", "PATCH"]);

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  json?: unknown;
  body?: BodyInit;
  accept?: string;
  signal?: AbortSignal;
}

export async function request(path: string, options: RequestOptions = {}): Promise<Response> {
  const method = options.method ?? "GET";
  const attempt = async () => {
    const token = await csrfToken();
    const headers: Record<string, string> = { Accept: options.accept ?? "application/json" };
    if (MUTATING.has(method)) headers["X-CSRF-Token"] = token;
    let body = options.body;
    if (options.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.json);
    }
    return send(path, { method, headers, body, signal: options.signal });
  };

  let res = await attempt();
  if (res.status === 401 || res.status === 403) {
    const error = await readError(res.clone());
    const expired = res.status === 401 && error.code === "session_required";
    if (expired || error.code === "csrf_failed") {
      resetSession();
      res = await attempt();
    }
  }
  if (!res.ok) throw await readError(res);
  return res;
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await request(path, { signal });
  return (await res.json()) as T;
}

async function sendJson<T>(method: "POST" | "PUT" | "DELETE", path: string, json?: unknown): Promise<T> {
  const res = await request(path, { method, json });
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return null;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : null;
}

const doc = (id: string) => `/api/documents/${encodeURIComponent(id)}`;

export const api = {
  health: (signal?: AbortSignal) => getJson<HealthResponse>("/api/health", signal),
  documents: (signal?: AbortSignal) => getJson<DocumentList>("/api/documents", signal),
  document: (id: string, signal?: AbortSignal) => getJson<DocumentSummary>(doc(id), signal),
  upload: async (file: File, mode: Mode): Promise<DocumentSummary> => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    const res = await request("/api/documents", { method: "POST", body: form });
    return (await res.json()) as DocumentSummary;
  },
  remove: (id: string) => sendJson<void>("DELETE", doc(id)),
  review: (id: string, signal?: AbortSignal) => getJson<ReviewPayload>(`${doc(id)}/review`, signal),
  pageMarks: (id: string, page: number, signal?: AbortSignal) =>
    getJson<PageMarks>(`${doc(id)}/pages/${page}/marks`, signal),
  pageImageUrl: (id: string, page: number) =>
    pageImageResolver ? pageImageResolver(id, page) : `${doc(id)}/pages/${page}`,
  decide: (id: string, body: DecisionRequest) => sendJson<ReviewPayload>("POST", `${doc(id)}/decisions`, body),
  approve: (id: string, body: ApproveRequest = {}) => sendJson<DocumentSummary>("POST", `${doc(id)}/approve`, body),
  reject: (id: string, body: RejectRequest) => sendJson<DocumentSummary>("POST", `${doc(id)}/reject`, body),
  download: async (id: string): Promise<{ blob: Blob; filename: string | null }> => {
    const res = await request(`${doc(id)}/download`, { accept: "application/pdf" });
    return { blob: await res.blob(), filename: filenameFrom(res.headers.get("Content-Disposition")) };
  },
  providers: (signal?: AbortSignal) => getJson<ProvidersResponse>("/api/chat/providers", signal),
  chatPreview: (body: ChatPreviewRequest) => sendJson<ChatPreviewResponse>("POST", "/api/chat/preview", body),
  chat: (body: ChatRequest) => sendJson<ChatResponse>("POST", "/api/chat", body),
  settings: (signal?: AbortSignal) => getJson<AppSettings>("/api/settings", signal),
  saveSettings: (body: AppSettings) => sendJson<AppSettings>("PUT", "/api/settings", body),
};
