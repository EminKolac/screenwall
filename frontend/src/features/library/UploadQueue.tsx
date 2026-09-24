import { useDocuments } from "../../api/queries";
import { statusLabel, tr } from "../../copy/tr";
import { cx } from "../../ui/cx";
import { Icon } from "../../ui/Icon";
import { IconButton } from "../../ui/IconButton";
import { Progress } from "../../ui/Progress";
import { progressFor } from "./filters";
import { useUploads, type UploadEntry } from "./uploadContext";
import s from "./UploadQueue.module.css";

function Entry({ entry }: { entry: UploadEntry }) {
  const { dismiss } = useUploads();
  const docs = useDocuments();
  const doc = entry.docId ? docs.data?.find((d) => d.id === entry.docId) : undefined;

  let stage: string = tr.upload.sending;
  let progress = 4;
  if (entry.phase === "failed") stage = tr.upload.failed;
  else if (doc) {
    stage = entry.phase === "done" && doc.status === "needs_review" ? tr.upload.ready : statusLabel[doc.status];
    progress = progressFor(doc.status);
  }

  return (
    <li className={cx(s.entry, entry.phase === "failed" && s.failed)}>
      <span className={s.icon} aria-hidden="true">
        <Icon name={entry.phase === "failed" ? "alert" : entry.phase === "done" ? "check" : "upload"} size={14} />
      </span>
      <span className={s.main}>
        <span className={s.name} title={entry.name}>
          {entry.name}
        </span>
        <span className={s.stage}>{entry.error ?? stage}</span>
        {entry.phase === "sending" || entry.phase === "accepted" ? (
          <Progress value={progress} label={`${entry.name}: ${stage}`} className={s.bar} />
        ) : null}
      </span>
      {entry.phase === "failed" ? (
        <IconButton icon="x" size="sm" label={tr.upload.dismiss(entry.name)} onClick={() => dismiss(entry.key)} />
      ) : null}
    </li>
  );
}

/** Transient list of this session's uploads; finished ones retire into the library. */
export function UploadQueue() {
  const { entries } = useUploads();
  if (!entries.length) return null;
  return (
    <section className={s.queue} aria-label={tr.upload.queueTitle}>
      <h2 className={s.title}>{tr.upload.queueTitle}</h2>
      <ul className={s.list} aria-live="polite">
        {entries.map((entry) => (
          <Entry key={entry.key} entry={entry} />
        ))}
      </ul>
    </section>
  );
}
