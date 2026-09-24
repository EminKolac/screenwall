// A fetch-compatible handler implementing every route of the contract against in-memory state.
import type { AppSettings, ApproveRequest, ChatPreviewRequest, ChatRequest, DecisionRequest, DocStatus, ErrorCode, RejectRequest } from "../contract";
import { answer, preview, PROVIDERS } from "./chat";
import { applyDecision } from "./decisions";
import { pageMarks, pageSvg } from "./pages";
import { buildPdf } from "./pdf";
import { allDocs, dropDoc, getDoc, getSettings, maskedText, putDoc, saveSettings, session, statusOf, toPayload, toSummary } from "./store";
import { createUploadedDoc, kindOf } from "./templates";
import type { MockDoc } from "./types";

type Handler = (match: RegExpMatchArray, init: RequestInit) => Promise<Response> | Response;

const MAX_UPLOAD = 50 * 1024 * 1024;
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fail = (status: number, code: ErrorCode) => json(status, { detail: code });
const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
const latency = (base: number) => wait(base + Math.round(Math.random() * base * 0.5));
const body = <T>(init: RequestInit): T => JSON.parse(typeof init.body === "string" ? init.body : "{}") as T;
const approved = (doc: MockDoc) => statusOf(doc) === "approved";
/** The client pinned a revision and the document has moved on since (span ids are positional). */
const stale = (doc: MockDoc, expected: number | undefined) => expected !== undefined && expected !== doc.revision;
/** Like the backend: no delete while it works on a document; a queued one is dropped (its job skipped). */
const BUSY: ReadonlySet<DocStatus> = new Set(["extracting", "masking", "auditing"]);

function withDoc(handler: (doc: MockDoc, match: RegExpMatchArray, init: RequestInit) => Promise<Response> | Response): Handler {
  return (match, init) => {
    const doc = getDoc(decodeURIComponent(match[1]));
    return doc ? handler(doc, match, init) : fail(404, "document_not_found");
  };
}

const routes: Array<[string, RegExp, Handler]> = [
  ["GET", /^\/api\/session$/, () => json(200, { csrf_token: session.csrf })],
  ["GET", /^\/api\/health$/, () => json(200, { status: "ok", auditor: { provider: "ollama", model: "qwen3.5:4b", reachable: true }, ocr: { available: true } })],
  ["GET", /^\/api\/documents$/, async () => {
    await latency(160);
    return json(200, { documents: allDocs().map((d) => toSummary(d)) });
  }],
  ["POST", /^\/api\/documents$/, async (_m, init) => {
    const form = init.body instanceof FormData ? init.body : null;
    const file = form?.get("file");
    if (!(file instanceof File)) return fail(400, "invalid_file");
    const kind = kindOf(file.name);
    if (!kind) return fail(415, "unsupported_file_type");
    if (file.size > MAX_UPLOAD) return fail(413, "file_too_large");
    await latency(320);
    const doc = createUploadedDoc(file.name, kind, form?.get("mode") === "destructive" ? "destructive" : "mapping", Date.now());
    putDoc(doc);
    return json(202, toSummary(doc));
  }],
  ["GET", /^\/api\/documents\/([^/]+)$/, withDoc((doc) => json(200, toSummary(doc)))],
  ["DELETE", /^\/api\/documents\/([^/]+)$/, withDoc(async (doc) => {
    if (BUSY.has(statusOf(doc))) return fail(409, "document_busy");
    await latency(200);
    dropDoc(doc.id);
    return new Response(null, { status: 204 });
  })],
  ["GET", /^\/api\/documents\/([^/]+)\/review$/, withDoc(async (doc) => {
    const status = statusOf(doc);
    if (status !== "needs_review" && status !== "approved") return fail(409, "not_in_review");
    await latency(240);
    return json(200, toPayload(doc));
  })],
  ["GET", /^\/api\/documents\/([^/]+)\/pages\/(\d+)$/, withDoc((doc, match) => {
    const page = doc.pages.find((p) => p.index === Number(match[2]));
    if (doc.mode === "destructive") return fail(409, "original_not_stored");
    if (!page) return fail(404, "page_not_found");
    return new Response(pageSvg(doc, page), { status: 200, headers: { "Content-Type": "image/svg+xml" } });
  })],
  ["GET", /^\/api\/documents\/([^/]+)\/pages\/(\d+)\/marks$/, withDoc(async (doc, match) => {
    const page = doc.pages.find((p) => p.index === Number(match[2]));
    if (doc.mode === "destructive") return fail(409, "original_not_stored");
    if (!page) return fail(404, "page_not_found");
    await latency(120);
    return json(200, pageMarks(doc, page));
  })],
  ["POST", /^\/api\/documents\/([^/]+)\/decisions$/, withDoc(async (doc, _m, init) => {
    if (statusOf(doc) !== "needs_review") return fail(409, "not_in_review");
    const request = body<DecisionRequest>(init);
    if (stale(doc, request.expected_revision)) return fail(409, "stale_revision");
    const settings = getSettings();
    const result = applyDecision(doc, request, settings);
    if (!result.ok) return fail(result.error === "original_not_stored" ? 409 : 400, result.error);
    await latency(200);
    putDoc(result.doc);
    saveSettings({ ...settings, ...result.lists });
    return json(200, toPayload(result.doc));
  })],
  ["POST", /^\/api\/documents\/([^/]+)\/approve$/, withDoc(async (doc, _m, init) => {
    if (statusOf(doc) !== "needs_review") return fail(409, "not_in_review");
    if (stale(doc, body<ApproveRequest>(init).expected_revision)) return fail(409, "stale_revision");
    if (doc.items.some((i) => i.status === "open")) return fail(409, "unresolved_items");
    await latency(260);
    const next: MockDoc = { ...doc, status: "approved", updatedAt: Date.now() };
    putDoc(next);
    return json(200, toSummary(next));
  })],
  ["POST", /^\/api\/documents\/([^/]+)\/reject$/, withDoc(async (doc, _m, init) => {
    if (statusOf(doc) !== "needs_review") return fail(409, "not_in_review");
    const reason = body<RejectRequest>(init).reason?.trim();
    await latency(200);
    const next: MockDoc = {
      ...doc,
      status: "rejected",
      updatedAt: Date.now(),
      reasons: [{ code: "rejected_by_user", text: reason ? `İnceleme notu: ${reason}` : "Belge incelemede reddedildi." }],
    };
    putDoc(next);
    return json(200, toSummary(next));
  })],
  ["GET", /^\/api\/documents\/([^/]+)\/masked$/, withDoc((doc) =>
    new Response(maskedText(doc), { status: 200, headers: { "Content-Type": "text/plain; charset=utf-8" } }),
  )],
  ["GET", /^\/api\/documents\/([^/]+)\/download$/, withDoc(async (doc) => {
    if (statusOf(doc) !== "approved") return fail(409, "not_approved");
    await latency(300);
    const name = `${doc.filename.replace(/\.[^.]+$/, "")}-maskeli.pdf`;
    const pdf = buildPdf(doc.filename, toPayload(doc).units.map((u) => u.masked));
    return new Response(pdf, {
      status: 200,
      headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(name)}` },
    });
  })],
  ["GET", /^\/api\/chat\/providers$/, async () => {
    await latency(140);
    return json(200, PROVIDERS);
  }],
  ["POST", /^\/api\/chat\/preview$/, async (_m, init) => {
    const request = body<ChatPreviewRequest>(init);
    const result = preview(request, request.doc_ids.map((id) => getDoc(id)), approved);
    await latency(260);
    return result.ok ? json(200, result.value) : fail(409, result.error);
  }],
  ["POST", /^\/api\/chat$/, async (_m, init) => {
    const request = body<ChatRequest>(init);
    const result = answer(request, request.doc_ids.map((id) => getDoc(id)), approved);
    await wait(result.ok ? result.value.elapsed_ms : 200);
    return result.ok ? json(200, result.value) : fail(409, result.error);
  }],
  ["GET", /^\/api\/settings$/, () => json(200, getSettings())],
  ["PUT", /^\/api\/settings$/, async (_m, init) => {
    await latency(180);
    return json(200, saveSettings(body<AppSettings>(init)));
  }],
];

export const requestLog: Array<{ method: string; path: string; at: number }> = [];

export async function mockFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const url = new URL(input, window.location.origin);
  const method = (init.method ?? "GET").toUpperCase();
  requestLog.push({ method, path: url.pathname, at: Date.now() });
  const route = routes.find(([m, pattern]) => m === method && pattern.test(url.pathname));
  if (!route) return fail(404, "internal_error");
  if (method !== "GET" && new Headers(init.headers).get("X-CSRF-Token") !== session.csrf) return fail(403, "csrf_failed");
  return route[2](url.pathname.match(route[1]) as RegExpMatchArray, init);
}
