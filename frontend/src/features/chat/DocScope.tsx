import { useId, useState } from "react";
import type { DocumentSummary } from "../../api/contract";
import { useDocuments } from "../../api/queries";
import { tr } from "../../copy/tr";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import s from "./Chat.module.css";

interface DocScopeProps {
  current: DocumentSummary;
  docIds: string[];
  onChange: (ids: string[]) => void;
}

/** Which approved documents the question covers. The open document is always included. */
export function DocScope({ current, docIds, onChange }: DocScopeProps) {
  const docs = useDocuments();
  const [open, setOpen] = useState(false);
  const listId = useId();
  const others = (docs.data ?? []).filter((d) => d.status === "approved" && d.id !== current.id);
  const selected = others.filter((d) => docIds.includes(d.id));

  const toggle = (id: string, on: boolean) =>
    onChange(on ? [...new Set([...docIds, id])] : docIds.filter((d) => d !== id || d === current.id));

  return (
    <div className={s.scope}>
      <span className={s.legend}>{tr.chat.scopeLabel}</span>
      <ul className={s.scopeChips}>
        <li className={s.scopeChip} title={current.filename}>
          <Icon name="file" size={13} />
          <span className={s.scopeName}>{current.filename}</span>
        </li>
        {selected.map((doc) => (
          <li key={doc.id} className={s.scopeChip} title={doc.filename}>
            <Icon name="file" size={13} />
            <span className={s.scopeName}>{doc.filename}</span>
            <button type="button" className={s.scopeRemove} aria-label={tr.chat.removeDoc(doc.filename)} onClick={() => toggle(doc.id, false)}>
              <Icon name="x" size={12} />
            </button>
          </li>
        ))}
      </ul>
      <Button size="sm" variant="quiet" icon="plus" aria-expanded={open} aria-controls={open ? listId : undefined} onClick={() => setOpen((v) => !v)}>
        {tr.chat.scopeAdd}
      </Button>
      {open ? (
        <fieldset id={listId} className={s.scopeList}>
          <legend className={s.scopeHint}>{tr.chat.scopeHint}</legend>
          {others.length ? (
            others.map((doc) => (
              <label key={doc.id} className={s.scopeOption}>
                <input type="checkbox" checked={docIds.includes(doc.id)} onChange={(event) => toggle(doc.id, event.target.checked)} />
                <span className={s.scopeName}>{doc.filename}</span>
              </label>
            ))
          ) : (
            <p className={s.scopeHint}>{tr.chat.scopeNone}</p>
          )}
        </fieldset>
      ) : null}
    </div>
  );
}
