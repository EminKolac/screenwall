import { useState, type KeyboardEvent } from "react";
import { api } from "../../api/client";
import { usePageMarks } from "../../api/queries";
import { familyLabel, tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { IconButton } from "../../ui/IconButton";
import { Skeleton } from "../../ui/Skeleton";
import { useReview } from "./reviewContext";
import s from "./PageView.module.css";

const ZOOM_MIN = 100;
const ZOOM_MAX = 250;
const ZOOM_STEP = 25;

/** The original page image with an SVG overlay of normalised mark rectangles. */
export function PageCanvas() {
  const { doc, payload, page, setPage, selection, select, model } = useReview();
  const info = payload.pages.find((p) => p.index === page) ?? payload.pages[0];
  const [zoom, setZoom] = useState(ZOOM_MIN);
  const [loaded, setLoaded] = useState<{ page: number; ok: boolean } | null>(null);
  const marks = usePageMarks(doc.id, info.index, true);
  const total = payload.pages.length;
  const ready = loaded?.page === info.index;

  const onRectKey = (event: KeyboardEvent<SVGRectElement>, ref: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(ref, "page");
    }
  };

  return (
    <div className={s.canvasPane}>
      <div className={s.toolbar}>
        <IconButton icon="chevronLeft" size="sm" label={tr.review.page.prev} disabled={info.index <= 1} onClick={() => setPage(info.index - 1)} />
        <span className={s.pageNum} aria-live="polite">
          <span className="sr-only">{tr.review.page.label(info.index)}</span>
          <span className="num" aria-hidden="true">
            {tr.review.page.of(info.index, total)}
          </span>
        </span>
        <IconButton icon="chevronRight" size="sm" label={tr.review.page.next} disabled={info.index >= total} onClick={() => setPage(info.index + 1)} />
        <span className={s.zoom}>
          <IconButton icon="zoomOut" size="sm" label={tr.review.page.zoomOut} disabled={zoom <= ZOOM_MIN} onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))} />
          <span className={cx("num", s.zoomValue)}>
            <span className="sr-only">{tr.review.page.zoomLabel} </span>
            {tr.review.page.zoom(zoom)}
          </span>
          <IconButton icon="zoomIn" size="sm" label={tr.review.page.zoomIn} disabled={zoom >= ZOOM_MAX} onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))} />
        </span>
      </div>
      <div className={s.canvasScroll}>
        <div className={s.canvas} style={{ width: `${zoom}%`, aspectRatio: `${info.width} / ${info.height}` }}>
          {!ready ? <Skeleton className={s.canvasSkeleton} height="100%" radius={2} /> : null}
          {ready && !loaded?.ok ? (
            <p className={s.imageError}>
              <Icon name="alert" size={16} />
              {tr.review.page.imageError}
            </p>
          ) : null}
          <img
            key={info.index}
            src={api.pageImageUrl(doc.id, info.index)}
            alt={tr.review.page.imageAlt(info.index)}
            className={s.image}
            draggable={false}
            onLoad={() => setLoaded({ page: info.index, ok: true })}
            onError={() => setLoaded({ page: info.index, ok: false })}
          />
          <svg className={s.overlay} viewBox="0 0 1 1" preserveAspectRatio="none" role="group" aria-label={tr.review.page.marksLabel}>
            {marks.data?.index === info.index
              ? marks.data.marks.map((mark) => {
                  const ref = model.marks.get(mark.ref);
                  const open = mark.kind === "suggestion" || mark.kind === "finding";
                  const label = `${familyLabel(ref?.family ?? null)} · ${tr.marks[mark.kind]}`;
                  return mark.rects.map(([x0, y0, x1, y1], i) => (
                    <rect
                      key={`${mark.ref}-${i}`}
                      x={x0}
                      y={y0}
                      width={Math.max(0, x1 - x0)}
                      height={Math.max(0, y1 - y0)}
                      className={cx(s.rect, s[mark.kind], selection.id === mark.ref && s.rectSelected)}
                      data-ref={mark.ref}
                      role={open && i === 0 ? "button" : undefined}
                      tabIndex={open && i === 0 ? 0 : undefined}
                      aria-label={open && i === 0 ? label : undefined}
                      onClick={() => select(mark.ref, "page")}
                      onKeyDown={open && i === 0 ? (event) => onRectKey(event, mark.ref) : undefined}
                    >
                      <title>{ref?.reason ? `${label} · ${ref.reason}` : label}</title>
                    </rect>
                  ));
                })
              : null}
          </svg>
        </div>
      </div>
    </div>
  );
}
