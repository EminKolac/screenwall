import { useId, useMemo, useState } from "react";
import type { Mode } from "../../api/contract";
import { useDocuments } from "../../api/queries";
import { modeText, tr } from "../../copy/tr";
import { isMockEnabled } from "../../api/mock/switch";
import { Badge } from "../../ui/Badge";
import { BrandMark } from "../../ui/BrandMark";
import { Button } from "../../ui/Button";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { IconButton } from "../../ui/IconButton";
import { DocumentList } from "./DocumentList";
import { countByFilter, FILTERS, filterDocs, type FilterId } from "./filters";
import { UploadQueue } from "./UploadQueue";
import { useUploads } from "./uploadContext";
import s from "./LibraryPane.module.css";

interface LibraryPaneProps {
  onOpenSettings: () => void;
  /** Present when the pane lives in the slide-over drawer. */
  onClose?: () => void;
  /** The phone/tablet home screen: the list is the page, the top bar carries brand and settings. */
  inline?: boolean;
}

export function LibraryPane({ onOpenSettings, onClose, inline = false }: LibraryPaneProps) {
  const docs = useDocuments();
  const { pick, mode, setMode } = useUploads();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterId>("all");
  const modeId = useId();
  const modeHintId = useId();
  const all = docs.data ?? [];
  const counts = useMemo(() => countByFilter(all), [all]);
  const visible = useMemo(() => filterDocs(all, query, filter), [all, query, filter]);

  return (
    <div className={cx(s.pane, inline && s.inline)}>
      {inline ? (
        <h1 className={s.inlineTitle}>{tr.library.title}</h1>
      ) : (
        <div className={s.head}>
          <span className={s.brand}>
            <BrandMark />
            {tr.app.name}
          </span>
          <span className={s.headActions}>
            <IconButton icon="settings" label={tr.app.settings} onClick={onOpenSettings} />
            {onClose ? <IconButton icon="x" label={tr.app.closeLibrary} onClick={onClose} /> : null}
          </span>
        </div>
      )}

      <div className={s.upload}>
        <Button variant="primary" icon="upload" onClick={pick} className={s.uploadButton} title={tr.library.uploadHint}>
          {tr.library.upload}
        </Button>
        <label className="sr-only" htmlFor={modeId}>
          {tr.library.modeLabel}
        </label>
        <span className={s.selectWrap}>
          <select
            id={modeId}
            className={s.select}
            value={mode}
            aria-describedby={modeHintId}
            title={modeText[mode].consequence}
            onChange={(event) => setMode(event.target.value as Mode)}
          >
            <option value="mapping">{modeText.mapping.label}</option>
            <option value="destructive">{modeText.destructive.label}</option>
          </select>
          <Icon name="chevronDown" size={14} className={s.chevron} />
        </span>
        <span id={modeHintId} className="sr-only">
          {modeText[mode].consequence}
        </span>
      </div>

      <UploadQueue />

      <div className={s.tools}>
        <label className={s.search}>
          <Icon name="search" size={15} className={s.searchIcon} />
          <input
            type="search"
            value={query}
            placeholder={tr.library.search}
            aria-label={tr.library.search}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className={s.chips} role="group" aria-label={tr.library.filtersLabel}>
          {FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              className={cx(s.chip, filter === id && s.chipOn)}
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {tr.library.filters[id]}
              <span className={s.chipCount}>{counts[id]}</span>
            </button>
          ))}
        </div>
      </div>

      <nav className={s.docs} aria-label={tr.library.listLabel}>
        <DocumentList
          docs={visible}
          loading={docs.isPending}
          error={docs.isError && !docs.data}
          onRetry={() => void docs.refetch()}
          filtered={Boolean(query.trim()) || filter !== "all"}
          onClearFilters={() => {
            setQuery("");
            setFilter("all");
          }}
          onOpen={onClose}
        />
      </nav>

      <footer className={s.foot}>
        {isMockEnabled() ? (
          <p className={s.footLine} title={tr.app.mockHint}>
            <Badge tone="info">{tr.app.mockBadge}</Badge>
            <span className={s.footMuted}>{tr.app.mockShort}</span>
          </p>
        ) : null}
        <p className={s.footLine}>
          <Icon name="shield" size={15} className={s.footIcon} />
          {tr.app.localFooter}
        </p>
      </footer>
    </div>
  );
}
