import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkedText, segment } from "./MarkedText";
import type { TextMark } from "./model";

const mark = (id: string, start: number, end: number, state: TextMark["state"]): TextMark => ({
  id,
  start,
  end,
  state,
  family: "PERSON",
  reason: "Test",
});

describe("MarkedText", () => {
  it("slices by code points, so emoji and Turkish letters keep marks in place", () => {
    const text = "🙂 Şükrü Öztürk İzmir'de yaşıyor.";
    const { container } = render(
      <p>
        <MarkedText text={text} marks={[mark("a", 2, 14, "masked"), mark("b", 15, 20, "suggestion")]} />
      </p>,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0]).toHaveTextContent("Şükrü Öztürk");
    expect(marks[1]).toHaveTextContent("İzmir");
    expect(container.textContent).toBe(text);
  });

  it("gives every state its class and data attribute", () => {
    const text = "aa bb cc dd ee";
    const states: TextMark["state"][] = ["masked", "suggestion", "finding", "kept", "added"];
    const { container } = render(
      <p>
        <MarkedText text={text} marks={states.map((state, i) => mark(state, i * 3, i * 3 + 2, state))} strikeKept />
      </p>,
    );
    for (const state of states) {
      const el = container.querySelector(`[data-mark-id="${state}"]`);
      expect(el).toHaveClass("mark", state);
      expect(el).toHaveAttribute("data-state", state);
    }
    expect(container.querySelector('[data-state="kept"]')).toHaveClass("strike");
  });

  it("renders masked-pane placeholders as chips and marks selection", () => {
    const { container } = render(
      <p>
        <MarkedText text="Ad: <PERSON_1>" marks={[mark("p", 4, 14, "masked")]} chips selectedId="p" onSelect={() => undefined} />
      </p>,
    );
    const chip = container.querySelector("mark");
    expect(chip).toHaveClass("chip", "selected");
    expect(chip).toHaveAttribute("role", "button");
    expect(chip).toHaveAccessibleName("<PERSON_1>, Kişi, maskelendi");
  });

  it("lets an open decision win an overlap and ignores out-of-range marks", () => {
    const parts = segment("abcdef", [mark("m", 0, 4, "masked"), mark("s", 2, 6, "suggestion"), mark("x", 3, 99, "added")]);
    expect(parts.map((p) => [p.text, p.mark?.id ?? null])).toEqual([
      ["ab", "m"],
      ["cdef", "s"],
    ]);
  });
});
