import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setTransport } from "./client";

const ok = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const detail = (code: string, status: number) => ok({ detail: code }, status);

function mockFetch(...replies: Array<Response | Error>) {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => {
    const next = replies.shift();
    if (!next) throw new Error("unexpected request");
    if (next instanceof Error) throw next;
    return next;
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const header = (init: RequestInit | undefined, name: string) => new Headers(init?.headers).get(name);

describe("api client", () => {
  beforeEach(() => setTransport(null));
  afterEach(() => vi.unstubAllGlobals());

  it("fetches the session once and sends X-CSRF-Token only on mutations", async () => {
    const fetch = mockFetch(ok({ csrf_token: "abc" }), ok({ documents: [] }), ok({ document: {} }), ok({}), new Response(null, { status: 204 }));
    await api.documents();
    await api.decide("d1", { op: "keep", target: { item_id: "i1" }, scope: "occurrence" });
    await api.saveSettings({ default_mode: "mapping", chat_default_provider: "ollama", always_mask: [], never_mask: [] });
    await api.remove("d1");

    const urls = fetch.mock.calls.map(([url]) => url);
    expect(urls).toEqual(["/api/session", "/api/documents", "/api/documents/d1/decisions", "/api/settings", "/api/documents/d1"]);
    const [, get, post, put, del] = fetch.mock.calls.map(([, init]) => init);
    expect(header(get, "X-CSRF-Token")).toBeNull();
    expect(header(post, "X-CSRF-Token")).toBe("abc");
    expect(header(put, "X-CSRF-Token")).toBe("abc");
    expect(header(del, "X-CSRF-Token")).toBe("abc");
    expect(post?.credentials).toBe("same-origin");
    expect(post?.method).toBe("POST");
  });

  it("re-opens the session and retries once after 401 session_required", async () => {
    const fetch = mockFetch(
      ok({ csrf_token: "old" }),
      detail("session_required", 401),
      ok({ csrf_token: "new" }),
      ok({ status: "approved" }),
    );
    await expect(api.approve("d1")).resolves.toEqual({ status: "approved" });
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/session", "/api/documents/d1/approve", "/api/session", "/api/documents/d1/approve"]);
    expect(header(fetch.mock.calls[3][1], "X-CSRF-Token")).toBe("new");
  });

  it("gives up after the single retry", async () => {
    mockFetch(ok({ csrf_token: "a" }), detail("session_required", 401), ok({ csrf_token: "b" }), detail("session_required", 401));
    await expect(api.approve("d1")).rejects.toMatchObject({ code: "session_required", status: 401 });
  });

  it("sends approve's ApproveRequest as JSON, an empty object by default", async () => {
    const fetch = mockFetch(ok({ csrf_token: "a" }), ok({ status: "approved" }), ok({ status: "approved" }));
    await api.approve("d1", { expected_revision: 4 });
    await api.approve("d1");
    const [, pinned, plain] = fetch.mock.calls.map(([, init]) => init);
    expect(header(pinned, "Content-Type")).toBe("application/json");
    expect(pinned?.body).toBe(JSON.stringify({ expected_revision: 4 }));
    expect(header(plain, "Content-Type")).toBe("application/json");
    expect(plain?.body).toBe("{}");
  });

  it("turns failures into ApiError codes", async () => {
    mockFetch(ok({ csrf_token: "a" }), detail("unresolved_items", 409), ok({ detail: [{ msg: "x" }] }, 422), new TypeError("offline"));
    const conflict = await api.approve("d1").catch((e: unknown) => e);
    expect(conflict).toBeInstanceOf(ApiError);
    expect(conflict).toMatchObject({ code: "unresolved_items", status: 409 });
    await expect(api.approve("d1")).rejects.toMatchObject({ code: "unknown_error", status: 422 });
    await expect(api.documents()).rejects.toMatchObject({ code: "network_error", status: 0 });
  });
});
