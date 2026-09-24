import { useId, useState } from "react";
import { tr } from "../../copy/tr";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import s from "./Settings.module.css";

interface TermListProps {
  title: string;
  terms: string[];
  onChange: (terms: string[]) => void;
}

function TermList({ title, terms, onChange }: TermListProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const headingId = useId();
  const inputId = useId();

  const add = () => {
    const term = value.trim();
    if (!term) return;
    const fold = term.toLocaleLowerCase("tr");
    if (terms.some((t) => t.toLocaleLowerCase("tr") === fold)) {
      setError(tr.settings.duplicate);
      return;
    }
    onChange([...terms, term]);
    setValue("");
    setError(null);
  };

  return (
    <div className={s.termList} role="group" aria-labelledby={headingId}>
      <h4 id={headingId} className={s.termTitle}>
        {title}
        <Badge tone="count">{terms.length}</Badge>
      </h4>
      {terms.length ? (
        <ul className={s.chips}>
          {terms.map((term) => (
            <li key={term} className={s.chip}>
              <span className={s.chipText}>{term}</span>
              <button type="button" className={s.chipRemove} aria-label={tr.settings.removeTerm(term)} onClick={() => onChange(terms.filter((t) => t !== term))}>
                <Icon name="x" size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={s.emptyList}>{tr.settings.emptyList}</p>
      )}
      <div className={s.addRow}>
        <label htmlFor={inputId} className="sr-only">
          {tr.settings.addTermLabel(title)}
        </label>
        <input
          id={inputId}
          className={s.textInput}
          value={value}
          placeholder={tr.settings.termPlaceholder}
          onChange={(event) => {
            setValue(event.target.value);
            setError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <Button size="sm" icon="plus" onClick={add} disabled={!value.trim()}>
          {tr.settings.addTerm}
        </Button>
      </div>
      {error ? (
        <p className={s.termError} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface TermListsProps {
  always: string[];
  never: string[];
  onChange: (always: string[], never: string[]) => void;
}

/** The global "always mask" / "never mask" lists. Empty by default. */
export function TermLists({ always, never, onChange }: TermListsProps) {
  return (
    <div className={s.termLists}>
      <TermList title={tr.settings.alwaysMask} terms={always} onChange={(next) => onChange(next, never)} />
      <TermList title={tr.settings.neverMask} terms={never} onChange={(next) => onChange(always, next)} />
    </div>
  );
}
