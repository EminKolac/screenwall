import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DocStatus } from "../api/contract";
import { StepBar, stepStates } from "./StepBar";

const expected: Record<DocStatus, string[]> = {
  queued: ["done", "current", "upcoming", "upcoming", "upcoming"],
  extracting: ["done", "current", "upcoming", "upcoming", "upcoming"],
  masking: ["done", "done", "current", "upcoming", "upcoming"],
  auditing: ["done", "done", "done", "current", "upcoming"],
  needs_review: ["done", "done", "done", "done", "current"],
  approved: ["done", "done", "done", "done", "done"],
  rejected: ["done", "done", "done", "done", "rejected"],
  failed: ["done", "failed", "upcoming", "upcoming", "upcoming"],
};

describe("StepBar", () => {
  it.each(Object.entries(expected))("maps %s to the right step states", (status, states) => {
    expect(stepStates(status as DocStatus)).toEqual(states);
    const { container } = render(<StepBar status={status as DocStatus} />);
    const items = container.querySelectorAll("li");
    expect(Array.from(items).map((li) => li.getAttribute("data-state"))).toEqual(states);
  });

  it("never draws 'Onay' as done while the document waits for review", () => {
    render(<StepBar status="needs_review" />);
    const approval = screen.getByText("Onay").closest("li")!;
    expect(approval).toHaveAttribute("aria-current", "step");
    expect(approval).toHaveAttribute("data-state", "current");
    expect(approval).toHaveTextContent("şu anki adım");
    expect(approval).not.toHaveTextContent("tamamlandı");
  });

  it("marks the failing step from the reason code", () => {
    expect(stepStates("failed", [{ code: "audit_failed", text: "x" }])).toEqual(["done", "done", "done", "failed", "upcoming"]);
    render(<StepBar status="failed" reasons={[{ code: "extraction_failed", text: "x" }]} />);
    expect(screen.getByText("Çıkarıldı").closest("li")).toHaveTextContent("başarısız");
  });
});
