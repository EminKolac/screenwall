import { useEffect, useRef } from "react";
import { tr } from "../../copy/tr";
import { MaskedUnit } from "./MaskedPane";
import { PageCanvas } from "./PageCanvas";
import { useReview } from "./reviewContext";
import { scrollToVisible } from "./SplitView";
import { TableGrid } from "./TableGrid";
import s from "./PageView.module.css";

/** Page view: the original page on the left, that page's masked text on the right. */
export function PageView() {
  const { model, page, pane, selection } = useReview();
  const root = useRef<HTMLDivElement>(null);
  const section = model.sections.find((sec) => sec.page === page);

  useEffect(() => {
    if (!selection.id || selection.source === "pane") return;
    scrollToVisible(root.current, `[data-pane="masked"] [data-mark-id="${selection.id}"]`, "nearest");
  }, [selection.nonce, selection.id, selection.source]);

  return (
    <div ref={root} className={s.pageView} data-show={pane}>
      <div className={s.pageOriginal} data-pane="original">
        <PageCanvas />
      </div>
      <div className={s.pageMasked} data-pane="masked">
        <div className={s.sheet}>
          {section && !section.empty ? (
            section.blocks.map((block) => (
              <div key={block.key} className={s.maskedRow}>
                {block.kind === "table" ? <TableGrid block={block} side="masked" /> : <MaskedUnit unit={block.unit} />}
              </div>
            ))
          ) : (
            <p className={s.noText}>{tr.review.page.noText}</p>
          )}
        </div>
      </div>
    </div>
  );
}
