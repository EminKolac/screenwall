import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import type { DecisionRequest } from "../../api/contract";
import { payload, renderApp, stubApi, summary } from "../../test/harness";
import { ReviewProvider } from "./reviewContext";
import { SelectionToolbar } from "./SelectionToolbar";
import { SplitView } from "./SplitView";
import { useSelectionMask } from "./useSelectionMask";

function Harness() {
  const root = useRef<HTMLDivElement>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const selection = useSelectionMask(root, toolbar);
  return (
    <div ref={root}>
      <SplitView />
      <SelectionToolbar selection={selection} toolbarRef={toolbar} />
    </div>
  );
}

function setup() {
  const doc = summary();
  const calls = stubApi({ "POST /api/documents/d1/decisions": payload(doc) });
  renderApp(
    <ReviewProvider doc={doc} payload={payload(doc)}>
      <Harness />
    </ReviewProvider>,
  );
  return calls;
}

/** Select characters [from, to) (UTF-16) of the last text node inside `element`. */
async function selectIn(element: Element, from: number, to: number) {
  const nodes = Array.from(element.childNodes).filter((n) => n.nodeType === Node.TEXT_NODE);
  const node = nodes[nodes.length - 1];
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(node, to);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  await act(async () => {
    fireEvent.mouseUp(element);
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
}

describe("selection toolbar", () => {
  it("appears for a selection in the original pane and masks it with code-point offsets", async () => {
    const calls = setup();
    const original = document.querySelector('[data-pane="original"] [data-unit-text="u1"]')!;
    await selectIn(original, 1, 6); // " İzmir'de…" → "İzmir"
    const toolbar = await screen.findByRole("toolbar", { name: "Seçimi maskele" });
    expect(toolbar).toHaveTextContent("İzmir");

    await userEvent.selectOptions(screen.getByLabelText("Tür"), "LOCATION");
    await userEvent.click(screen.getByRole("button", { name: "Maskele" }));

    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/decisions"))).toBe(true));
    const sent = calls.find((c) => c.url.endsWith("/decisions"))!;
    expect(sent.headers.get("X-CSRF-Token")).toBe("token-1");
    expect(sent.body as DecisionRequest).toEqual({
      op: "mask",
      target: { unit_id: "u1", start: 15, end: 20, family: "LOCATION" },
      scope: "document",
      expected_revision: 1,
    });
  });

  it("stays hidden for a selection in the masked pane", async () => {
    setup();
    const masked = document.querySelector('[data-pane="masked"] [data-unit-masked="u1"]')!;
    await selectIn(masked, 1, 6);
    expect(screen.queryByRole("toolbar")).toBeNull();
  });

  it("refuses a selection that overlaps a masked value", async () => {
    setup();
    const original = document.querySelector('[data-pane="original"] [data-unit-text="u1"] mark')!;
    await selectIn(original, 0, 5);
    expect(await screen.findByRole("toolbar")).toHaveTextContent("Seçim maskeli bir alanla çakışıyor");
    expect(screen.getByRole("button", { name: "Maskele" })).toBeDisabled();
  });
});
