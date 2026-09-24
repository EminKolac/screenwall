import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { DecisionRequest, ReviewItem, ReviewPayload } from "../../api/contract";
import { useDocuments, usePageMarks, useReviewPayload } from "../../api/queries";
import { errorText } from "../../copy/tr";
import { payload, renderApp, stubApi, summary, type Call } from "../../test/harness";
import { ReviewDialogs } from "./ReviewDialogs";
import { ReviewProvider, useReview } from "./reviewContext";

const STALE_TOAST = "Belge bu arada değişti; güncel hâli yüklendi.";
const AUDIT_TOAST = "Denetim yeni bir uyarı verdi; gözden geçirip yeniden onaylayın.";

/** The server side of the test: the document's current revision, moved on by the test at will. */
interface Server {
  revision: number;
}

const at = (revision: number): ReviewPayload => payload(summary({ revision }));
const conflict = (code: string, status = 409) => () => Response.json({ detail: code }, { status });

/** A residual a fresh audit located in u1: "İzmir" (original 15–20, masked 13–18). */
const residual: ReviewItem = {
  id: "i1",
  kind: "finding",
  unit_id: "u1",
  start: 15,
  end: 20,
  masked_start: 13,
  masked_end: 18,
  family: "LOCATION",
  reason: "Denetim: konum olabilir",
  occurrences: 1,
  status: "open",
};

const MARKS = "/api/documents/d1/pages/1/marks";
const count = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url).length;
const reviewGets = (calls: Call[]) => count(calls, "GET", "/api/documents/d1/review");
const listGets = (calls: Call[]) => count(calls, "GET", "/api/documents");
const sent = (calls: Call[], path: string) => calls.filter((c) => c.method === "POST" && c.url === `/api/documents/d1/${path}`);

function routes(server: Server, extra: Record<string, unknown>) {
  return {
    "GET /api/documents": () => ({ documents: [summary({ revision: server.revision })] }),
    "GET /api/documents/d1/review": () => at(server.revision),
    ...extra,
  };
}

/** Like ReviewLoader: the review stays an active query, so invalidating it really refetches. */
function Live({ children }: { children: ReactNode }) {
  const docs = useDocuments();
  const review = useReviewPayload("d1", true);
  const doc = docs.data?.find((d) => d.id === "d1");
  if (!doc || !review.data) return null;
  return (
    <ReviewProvider doc={doc} payload={review.data}>
      {children}
    </ReviewProvider>
  );
}

/** Keeps a page-marks query active, as the page view does. */
function Marks() {
  usePageMarks("d1", 1, true);
  return null;
}

function Probe() {
  const { payload: shown, decide, setDialog } = useReview();
  return (
    <>
      <output data-testid="revision">{shown.document.revision}</output>
      <output data-testid="open">{shown.items.filter((i) => i.status === "open").length}</output>
      <button type="button" onClick={() => void decide({ op: "unmask", target: { span_id: "s1" }, scope: "occurrence" })}>
        decide
      </button>
      <button type="button" onClick={() => setDialog("approve")}>
        open approve
      </button>
      <ReviewDialogs />
    </>
  );
}

function setup(server: Server, extra: Record<string, unknown>) {
  const calls = stubApi(routes(server, extra));
  renderApp(
    <Live>
      <Probe />
    </Live>,
  );
  return calls;
}

const shownRevision = () => screen.getByTestId("revision").textContent;
const openItems = () => screen.getByTestId("open").textContent;

async function confirmApproval() {
  await userEvent.click(await screen.findByRole("button", { name: "open approve" }));
  const dialog = await screen.findByRole("dialog", { name: "Belgeyi onayla" });
  await userEvent.click(within(dialog).getByRole("button", { name: "Onayla" }));
}

describe("decisions carry the payload revision", () => {
  it("sends expected_revision from the payload on screen, following it after each decision", async () => {
    const server = { revision: 5 };
    const calls = setup(server, {
      "POST /api/documents/d1/decisions": () => at(++server.revision),
    });

    await userEvent.click(await screen.findByRole("button", { name: "decide" }));
    await waitFor(() => expect(shownRevision()).toBe("6"));
    await userEvent.click(screen.getByRole("button", { name: "decide" }));
    await waitFor(() => expect(sent(calls, "decisions")).toHaveLength(2));

    const bodies = sent(calls, "decisions").map((c) => c.body as DecisionRequest);
    expect(bodies.map((b) => b.expected_revision)).toEqual([5, 6]);
    expect(bodies[0]).toEqual({ op: "unmask", target: { span_id: "s1" }, scope: "occurrence", expected_revision: 5 });
  });

  it("reloads the review on 409 stale_revision and says so instead of showing an error", async () => {
    const server = { revision: 1 };
    const calls = setup(server, { "POST /api/documents/d1/decisions": conflict("stale_revision") });
    await screen.findByRole("button", { name: "decide" });
    server.revision = 3; // the document was re-anonymized behind the person's back

    await userEvent.click(screen.getByRole("button", { name: "decide" }));

    expect(await screen.findByText(STALE_TOAST)).toBeInTheDocument();
    // The toast waits for the reload: both refetches have already happened when it shows.
    expect(reviewGets(calls)).toBe(2);
    expect(listGets(calls)).toBe(2);
    await waitFor(() => expect(shownRevision()).toBe("3"));
    expect(screen.queryByText(errorText.stale_revision)).toBeNull();
    expect((sent(calls, "decisions")[0].body as DecisionRequest).expected_revision).toBe(1);
  });
});

describe("the pinned revision is the payload's, never the library list's", () => {
  // The list can already know a newer revision than the payload being looked at. Pinning the list's
  // revision would let the server accept span ids that were read from the older payload.
  const lagging = () =>
    setup(
      { revision: 5 },
      {
        "GET /api/documents": { documents: [summary({ revision: 9 })] },
        "POST /api/documents/d1/decisions": conflict("stale_revision"),
        "POST /api/documents/d1/approve": conflict("stale_revision"),
      },
    );

  it("for a decision", async () => {
    const calls = lagging();
    await userEvent.click(await screen.findByRole("button", { name: "decide" }));
    expect(await screen.findByText(STALE_TOAST)).toBeInTheDocument();
    expect(sent(calls, "decisions").map((c) => (c.body as DecisionRequest).expected_revision)).toEqual([5]);
  });

  it("for approval", async () => {
    const calls = lagging();
    await confirmApproval();
    expect(await screen.findByText(STALE_TOAST)).toBeInTheDocument();
    expect(sent(calls, "approve").map((c) => c.body)).toEqual([{ expected_revision: 5 }]);
  });
});

describe("approval carries the payload revision", () => {
  it("sends {expected_revision} from the payload on screen", async () => {
    const server = { revision: 4 };
    const calls = setup(server, {
      "POST /api/documents/d1/approve": () => summary({ revision: 4, status: "approved" }),
    });

    await confirmApproval();

    expect(await screen.findByText("Belge onaylandı")).toBeInTheDocument();
    expect(sent(calls, "approve").map((c) => c.body)).toEqual([{ expected_revision: 4 }]);
  });

  it("reloads the review on 409 stale_revision, closes the dialog and says so", async () => {
    const server = { revision: 2 };
    const calls = setup(server, { "POST /api/documents/d1/approve": conflict("stale_revision") });
    await screen.findByRole("button", { name: "open approve" });
    server.revision = 3;

    await confirmApproval();

    expect(await screen.findByText(STALE_TOAST)).toBeInTheDocument();
    expect(reviewGets(calls)).toBe(2);
    expect(listGets(calls)).toBe(2);
    expect(sent(calls, "approve").map((c) => c.body)).toEqual([{ expected_revision: 2 }]);
    await waitFor(() => expect(shownRevision()).toBe("3"));
    expect(screen.queryByRole("dialog", { name: "Belgeyi onayla" })).toBeNull();
    expect(screen.queryByText(errorText.stale_revision)).toBeNull();
  });

  it("reloads the review on 409 audit_not_clean and asks for a fresh look before approving again", async () => {
    const server = { revision: 1 };
    const calls = setup(server, { "POST /api/documents/d1/approve": conflict("audit_not_clean") });

    await confirmApproval();

    expect(await screen.findByText(AUDIT_TOAST)).toBeInTheDocument();
    expect(reviewGets(calls)).toBe(2);
    expect(listGets(calls)).toBe(2);
    expect(screen.queryByRole("dialog", { name: "Belgeyi onayla" })).toBeNull();
    expect(screen.queryByText(errorText.audit_not_clean)).toBeNull();
  });

  it("reloads the review on 409 unresolved_items from a fresh audit, so the new finding shows, and says why", async () => {
    const server = { revision: 1 };
    const calls = stubApi(
      routes(server, {
        "GET /api/documents/d1/review": () => ({ ...at(server.revision), items: server.revision > 1 ? [residual] : [] }),
        [`GET ${MARKS}`]: { index: 1, width: 595, height: 842, marks: [] },
        "POST /api/documents/d1/approve": () => {
          server.revision = 2; // the fresh audit stored the residual as a finding and bumped the revision
          return Response.json({ detail: "unresolved_items" }, { status: 409 });
        },
      }),
    );
    renderApp(
      <>
        <Marks />
        <Live>
          <Probe />
        </Live>
      </>,
    );
    await waitFor(() => expect(count(calls, "GET", MARKS)).toBe(1));
    expect(openItems()).toBe("0");

    await confirmApproval();

    expect(await screen.findByText(errorText.unresolved_items)).toBeInTheDocument();
    expect(reviewGets(calls)).toBe(2);
    expect(listGets(calls)).toBe(2);
    expect(count(calls, "GET", MARKS)).toBe(2);
    await waitFor(() => expect(openItems()).toBe("1"));
    expect(shownRevision()).toBe("2");
    expect(screen.queryByRole("dialog", { name: "Belgeyi onayla" })).toBeNull();
  });

  it("keeps the generic error toast, and the dialog, for other failures", async () => {
    const server = { revision: 1 };
    const calls = setup(server, { "POST /api/documents/d1/approve": conflict("ollama_unreachable", 503) });

    await confirmApproval();

    expect(await screen.findByText(errorText.ollama_unreachable)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Belgeyi onayla" })).toBeInTheDocument();
    expect(reviewGets(calls)).toBe(1);
  });
});
