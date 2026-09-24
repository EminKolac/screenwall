import { useEffect, useRef, useState } from "react";
import { tr } from "../../copy/tr";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { MaskedUnit } from "./MaskedPane";
import type { Block, ReviewModel } from "./model";
import { DestructiveNotice, OriginalUnit } from "./OriginalPane";
import { useReview } from "./reviewContext";
import { TableGrid } from "./TableGrid";
import s from "./SplitView.module.css";

const smooth = (): ScrollBehavior =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

/** Scroll the first *visible* match (the other pane may be hidden on small screens). */
export function scrollToVisible(root: HTMLElement | null, selector: string, block: ScrollLogicalPosition = "center") {
  if (!root) return;
  const matches = Array.from(root.querySelectorAll<HTMLElement>(selector));
  const target = matches.find((el) => el.offsetParent !== null) ?? matches[0];
  target?.scrollIntoView?.({ block, behavior: smooth() });
}

function blockOf(model: ReviewModel, unitId: string): string | null {
  for (const section of model.sections)
    for (const block of section.blocks) {
      if (block.kind === "unit" && block.unit.id === unitId) return block.key;
      if (block.kind === "table" && block.rows.some((row) => row.some((cell) => cell?.id === unitId))) return block.key;
    }
  return null;
}

function Row({ block, destructive, flash }: { block: Block; destructive: boolean; flash: boolean }) {
  if (block.kind === "table" && !destructive) {
    return (
      <div className={s.tableRow} data-row={block.key} data-flash={flash || undefined}>
        <TableGrid block={block} side="both" />
      </div>
    );
  }
  return (
    <div className={s.row} data-row={block.key} data-flash={flash || undefined}>
      {destructive ? null : (
        <div className={s.cellOriginal} data-pane="original">
          {block.kind === "table" ? <TableGrid block={block} side="original" /> : <OriginalUnit unit={block.unit} />}
        </div>
      )}
      <div className={s.cellMasked} data-pane="masked">
        {block.kind === "table" ? <TableGrid block={block} side="masked" /> : <MaskedUnit unit={block.unit} />}
      </div>
    </div>
  );
}

function UnreadablePage({ page }: { page: number | null }) {
  const { payload, setView, setPage, destructive } = useReview();
  const canShow = page !== null && payload.pages.length > 0 && !destructive;
  return (
    <div className={s.unreadable}>
      <Icon name="alert" size={16} />
      <span>{tr.review.page.noText}</span>
      {canShow ? (
        <Button
          size="sm"
          variant="quiet"
          icon="page"
          onClick={() => {
            setPage(page);
            setView("page");
          }}
        >
          {tr.review.panes.page}
        </Button>
      ) : null}
    </div>
  );
}

/** Text view: each unit is one row with its original and masked halves side by side. */
export function SplitView() {
  const { model, destructive, pane, selection, unitFocus } = useReview();
  const root = useRef<HTMLDivElement>(null);
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    if (!selection.id || selection.source === "pane") return;
    scrollToVisible(root.current, `[data-mark-id="${selection.id}"]`);
  }, [selection.nonce, selection.id, selection.source]);

  useEffect(() => {
    if (!unitFocus) return;
    setFlash(blockOf(model, unitFocus.unitId));
    const frame = requestAnimationFrame(() =>
      scrollToVisible(root.current, `[data-unit-masked="${unitFocus.unitId}"]`),
    );
    const timer = window.setTimeout(() => setFlash(null), 1800);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
    // Only a new focus request (nonce) should re-run this.
  }, [unitFocus?.nonce]);

  return (
    <div ref={root} className={cx(s.split, destructive && s.destructive)} data-show={destructive ? "masked" : pane}>
      {destructive ? <DestructiveNotice /> : null}
      <div className={s.sections}>
        {model.sections.map((section) => (
          <section key={section.key} className={s.section}>
            <h2 className={s.sectionLabel}>{section.label}</h2>
            <div className={s.sheet}>
              {section.empty ? (
                <UnreadablePage page={section.page} />
              ) : (
                section.blocks.map((block) => (
                  <Row key={block.key} block={block} destructive={destructive} flash={flash === block.key} />
                ))
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
