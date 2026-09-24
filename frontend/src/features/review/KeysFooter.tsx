import { Fragment } from "react";
import { tr } from "../../copy/tr";
import { Kbd } from "../../ui/Kbd";
import { NARROW_QUERY, useMediaQuery } from "../../ui/useMediaQuery";
import s from "./ReviewWorkspace.module.css";

/** The quiet shortcut bar under the panes. Hidden on phones, where there is no keyboard. */
export function KeysFooter({ onHelp }: { onHelp: () => void }) {
  const narrow = useMediaQuery(NARROW_QUERY);
  if (narrow) return null;
  return (
    <div className={s.keys}>
      <span className="sr-only">{tr.keys.footerLabel}: </span>
      {tr.keys.footer.map((item) => (
        <span key={item.text} className={s.key}>
          {item.keys.map((key, i) => (
            <Fragment key={key}>
              {i > 0 ? <span aria-hidden="true">/</span> : null}
              <Kbd>{key}</Kbd>
            </Fragment>
          ))}
          {item.text}
        </span>
      ))}
      <button type="button" className={s.keysHelp} onClick={onHelp}>
        {tr.keys.dialogTitle}
      </button>
    </div>
  );
}
