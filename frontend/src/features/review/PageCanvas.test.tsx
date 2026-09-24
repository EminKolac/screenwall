import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PageMarks, ReviewPayload } from "../../api/contract";
import { payload, renderApp, stubApi, summary } from "../../test/harness";
import { PageCanvas } from "./PageCanvas";
import { ReviewProvider } from "./reviewContext";

function withPages(): ReviewPayload {
  const doc = summary({ kind: "pdf", pages: 2 });
  const base = payload(doc);
  return { ...base, units: base.units.map((u) => ({ ...u, page: 1 })), pages: [{ index: 1, width: 600, height: 800 }, { index: 2, width: 600, height: 800 }] };
}

function renderCanvas(marks: PageMarks["marks"]) {
  const data = withPages();
  stubApi({ "GET /api/documents/d1/pages/1/marks": { index: 1, width: 600, height: 800, marks } });
  return renderApp(
    <ReviewProvider doc={data.document} payload={data}>
      <PageCanvas />
    </ReviewProvider>,
  );
}

describe("PageCanvas", () => {
  it("draws normalised rectangles per mark kind over the page image", async () => {
    const { container } = renderCanvas([
      { ref: "s1", kind: "masked", rects: [[0.1, 0.2, 0.4, 0.25]] },
      { ref: "i1", kind: "suggestion", rects: [[0.5, 0.3, 0.7, 0.34], [0.1, 0.35, 0.2, 0.39]] },
    ]);
    expect(screen.getByRole("img", { name: "Orijinal belge, sayfa 1" })).toHaveAttribute("src", "/api/documents/d1/pages/1");
    await waitFor(() => expect(container.querySelectorAll("rect")).toHaveLength(3));
    const masked = container.querySelector('rect[data-ref="s1"]')!;
    expect(masked).toHaveClass("rect", "masked");
    expect(masked.getAttribute("x")).toBe("0.1");
    expect(Number(masked.getAttribute("width"))).toBeCloseTo(0.3);
    expect(container.querySelector("svg[viewBox='0 0 1 1']")).toHaveAttribute("preserveAspectRatio", "none");
    // Open decisions are reachable by keyboard, once per mark.
    expect(screen.getAllByRole("button", { name: /öneri, karar bekliyor/ })).toHaveLength(1);
  });

  it("does not invent coordinates when the page has no marks", async () => {
    const { container } = renderCanvas([]);
    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());
    expect(container.querySelector("rect")).toBeNull();
    expect(screen.getByRole("button", { name: "Önceki sayfa" })).toBeDisabled();
  });
});
