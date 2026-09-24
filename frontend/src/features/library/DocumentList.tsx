import { NavLink } from "react-router-dom";
import type { DocumentSummary } from "../../api/contract";
import { isProcessing } from "../../api/queries";
import { statusLabel, tr } from "../../copy/tr";
import { docPath } from "../../app/paths";
import { Button } from "../../ui/Button";
import { KindIcon } from "../../ui/KindIcon";
import { Progress } from "../../ui/Progress";
import { Skeleton } from "../../ui/Skeleton";
import { StatusPill } from "../../ui/StatusPill";
import { progressFor, reasonLine } from "./filters";
import s from "./DocumentList.module.css";

function DocumentRow({ doc, onOpen }: { doc: DocumentSummary; onOpen?: () => void }) {
  const reason = reasonLine(doc);
  const processing = isProcessing(doc.status);
  // "2 karar bekliyor" already says "in review"; it replaces the status word instead of trailing it.
  const lead = doc.status === "needs_review" ? reason ?? undefined : undefined;
  const trailing = lead ? null : reason;
  return (
    <li>
      <NavLink to={docPath(doc.id)} className={s.row} title={doc.filename} onClick={onOpen}>
        <KindIcon kind={doc.kind} />
        <span className={s.main}>
          <span className={s.name}>{doc.filename}</span>
          <span className={s.meta}>
            <StatusPill status={doc.status} label={lead} title={lead} className={lead ? s.pillLead : s.pillFixed} />
            {trailing ? (
              <>
                <span className={s.sep} aria-hidden="true">
                  ·
                </span>
                <span className={s.reason} title={doc.reasons.map((r) => r.text).join(" ") || trailing}>
                  {trailing}
                </span>
              </>
            ) : null}
          </span>
          {processing ? (
            <Progress
              value={progressFor(doc.status)}
              label={`${tr.library.progress}: ${statusLabel[doc.status]}`}
              className={s.progress}
            />
          ) : null}
        </span>
      </NavLink>
    </li>
  );
}

interface DocumentListProps {
  docs: DocumentSummary[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  filtered: boolean;
  onClearFilters: () => void;
  onOpen?: () => void;
}

export function DocumentList({ docs, loading, error, onRetry, filtered, onClearFilters, onOpen }: DocumentListProps) {
  if (loading) {
    return (
      <ul className={s.list} aria-busy="true" aria-label={tr.library.listLabel}>
        {[0, 1, 2, 3].map((i) => (
          <li key={i} className={s.skeletonRow}>
            <Skeleton width={26} height={32} radius={4} />
            <span className={s.main}>
              <Skeleton width={`${78 - i * 9}%`} height={12} />
              <Skeleton width="46%" height={10} />
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (error) {
    return (
      <div className={s.note} role="alert">
        <p>{tr.library.loadError}</p>
        <Button size="sm" icon="refresh" onClick={onRetry}>
          {tr.common.retry}
        </Button>
      </div>
    );
  }
  if (!docs.length) {
    return (
      <div className={s.note}>
        <p>{filtered ? tr.library.noMatch : tr.library.empty}</p>
        {filtered ? (
          <Button size="sm" variant="quiet" onClick={onClearFilters}>
            {tr.library.clearFilters}
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <ul className={s.list}>
      {docs.map((doc) => (
        <DocumentRow key={doc.id} doc={doc} onOpen={onOpen} />
      ))}
    </ul>
  );
}
