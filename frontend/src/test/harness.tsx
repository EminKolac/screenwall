import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import type { DocumentSummary, ReviewPayload } from "../api/contract";
import { setTransport } from "../api/client";
import { ToastProvider } from "../ui/Toast";

export interface Call {
  method: string;
  url: string;
  headers: Headers;
  body: unknown;
}

type Reply = unknown | ((body: unknown) => unknown) | Response;

/**
 * Routes "METHOD /path" to canned JSON; records every call; /api/session is built in.
 * A function reply runs per call and may return a Response (e.g. a 409) instead of JSON.
 */
export function stubApi(routes: Record<string, Reply>) {
  const calls: Call[] = [];
  setTransport(async (url, init) => {
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body ?? null;
    calls.push({ method, url, headers: new Headers(init.headers), body });
    if (url === "/api/session") return Response.json({ csrf_token: "token-1" });
    const reply = routes[`${method} ${url}`];
    if (reply === undefined) return Response.json({ detail: "internal_error" }, { status: 500 });
    if (reply instanceof Response) return reply;
    const value = typeof reply === "function" ? (reply as (b: unknown) => unknown)(body) : reply;
    return value instanceof Response ? value : Response.json(value);
  });
  return calls;
}

export function renderApp(ui: ReactElement, route = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          {ui}
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

export function summary(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "d1",
    filename: "Deneme.docx",
    kind: "docx",
    mode: "mapping",
    language: "tr",
    status: "needs_review",
    revision: 1,
    created_at: "2026-09-24T09:00:00Z",
    updated_at: "2026-09-24T09:00:00Z",
    pages: null,
    counts: { masked: 1, pending: 0 },
    reasons: [],
    can: { review: true, approve: true, download: false, chat: false, decide: true },
    ...overrides,
  };
}

/** One unit with an emoji and Turkish letters before a masked name: "🙂 Şükrü Öztürk İzmir'de yaşıyor." */
export function payload(doc = summary()): ReviewPayload {
  return {
    document: doc,
    units: [
      {
        id: "u1",
        block_id: "b1",
        kind: "paragraph",
        page: null,
        location: "Bölüm 1",
        table: null,
        original: "🙂 Şükrü Öztürk İzmir'de yaşıyor.",
        masked: "🙂 <PERSON_1> İzmir'de yaşıyor.",
      },
    ],
    spans: [
      {
        id: "s1",
        unit_id: "u1",
        start: 2,
        end: 14,
        masked_start: 2,
        masked_end: 12,
        family: "PERSON",
        placeholder: "<PERSON_1>",
        evidence: ["recognizer:PERSON"],
        reason: "İsim sözlüğü",
        state: "masked",
      },
    ],
    items: [],
    pages: [],
  };
}
