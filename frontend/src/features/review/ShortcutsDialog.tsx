import { Fragment } from "react";
import { tr } from "../../copy/tr";
import { Dialog } from "../../ui/Dialog";
import { Kbd } from "../../ui/Kbd";
import s from "./WorkspaceHeader.module.css";

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} size="sm" title={tr.keys.dialogTitle} description={tr.keys.dialogBody}>
      <dl className={s.shortcuts}>
        {tr.keys.list.map((item) => (
          <Fragment key={item.text}>
            <dt>
              {item.keys.map((key) => (
                <Kbd key={key}>{key}</Kbd>
              ))}
            </dt>
            <dd>{item.text}</dd>
          </Fragment>
        ))}
      </dl>
    </Dialog>
  );
}
