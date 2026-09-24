import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DocStatus } from "../../api/contract";
import { useDocuments } from "../../api/queries";
import { errorText } from "../../copy/tr";
import { payload, renderApp, stubApi, summary, type Call } from "../../test/harness";
import { DeleteDialog } from "./DeleteDialog";
import { ReviewProvider } from "./reviewContext";
import { StatusView } from "./StatusView";
import { WorkspaceHeader } from "./WorkspaceHeader";

const PROCESSING: DocStatus[] = ["queued", "extracting", "masking", "auditing"];
const SETTLED: DocStatus[] = ["needs_review", "approved", "rejected", "failed"];
const NOT_REVIEWABLE = { review: false, approve: false, download: false, chat: false, decide: false };

const deletes = (calls: Call[]) => calls.filter((c) => c.method === "DELETE");
const listGets = (calls: Call[]) => calls.filter((c) => c.method === "GET" && c.url === "/api/documents").length;

/** Keeps the library query active, as the app's library pane does. */
function Library() {
  useDocuments();
  return null;
}

function openDialog(status: DocStatus, routes: Record<string, unknown> = {}) {
  const calls = stubApi({ "DELETE /api/documents/d1": () => new Response(null, { status: 204 }), ...routes });
  renderApp(<DeleteDialog doc={summary({ status })} open onClose={() => undefined} />);
  return { calls, dialog: screen.getByRole("dialog", { name: "Belgeyi sil" }) };
}

describe("delete dialog", () => {
  it.each(PROCESSING)("cannot be confirmed while the document is %s", async (status) => {
    const { calls, dialog } = openDialog(status);
    const confirm = within(dialog).getByRole("button", { name: "Sil" });

    expect(confirm).toBeDisabled();
    expect(dialog).toHaveTextContent(errorText.document_busy);
    await userEvent.click(confirm);
    expect(deletes(calls)).toHaveLength(0);
  });

  it.each(SETTLED)("deletes a %s document after confirmation", async (status) => {
    const { calls, dialog } = openDialog(status);

    await userEvent.click(within(dialog).getByRole("button", { name: "Sil" }));

    expect(await screen.findByText("Belge silindi")).toBeInTheDocument();
    expect(deletes(calls).map((c) => c.url)).toEqual(["/api/documents/d1"]);
  });

  it("shows the busy sentence on 409 document_busy and refetches the library's real status", async () => {
    const calls = stubApi({
      "GET /api/documents": { documents: [summary()] },
      "DELETE /api/documents/d1": () => Response.json({ detail: "document_busy" }, { status: 409 }),
    });
    renderApp(
      <>
        <Library />
        <DeleteDialog doc={summary()} open onClose={() => undefined} />
      </>,
    );
    await waitFor(() => expect(listGets(calls)).toBe(1));

    await userEvent.click(within(screen.getByRole("dialog", { name: "Belgeyi sil" })).getByRole("button", { name: "Sil" }));

    expect(await screen.findByText(errorText.document_busy)).toBeInTheDocument();
    await waitFor(() => expect(listGets(calls)).toBe(2));
    expect(screen.queryByText("Belge silindi")).toBeNull();
  });
});

describe("delete entry points", () => {
  it.each(PROCESSING)("the status screen offers no delete while the document is %s", (status) => {
    stubApi({});
    renderApp(<StatusView doc={summary({ status, can: NOT_REVIEWABLE })} />);
    expect(screen.queryByRole("button", { name: "Sil" })).toBeNull();
  });

  it.each<DocStatus>(["failed", "rejected"])("the status screen offers delete once the document is %s", (status) => {
    stubApi({});
    renderApp(<StatusView doc={summary({ status, can: NOT_REVIEWABLE })} />);
    expect(screen.getByRole("button", { name: "Sil" })).toBeEnabled();
  });

  it.each(PROCESSING)("the review header has no delete menu while the document is %s", (status) => {
    stubApi({});
    const doc = summary({ status });
    renderApp(
      <ReviewProvider doc={doc} payload={payload(doc)}>
        <WorkspaceHeader />
      </ReviewProvider>,
    );
    expect(screen.queryByRole("button", { name: "Diğer işlemler" })).toBeNull();
  });

  it("the review header offers delete through its menu for a document in review", async () => {
    stubApi({});
    const doc = summary();
    renderApp(
      <ReviewProvider doc={doc} payload={payload(doc)}>
        <WorkspaceHeader />
      </ReviewProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Diğer işlemler" }));
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Sil" })).toBeInTheDocument());
  });
});
