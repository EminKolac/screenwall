import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { isProcessing, useDocuments } from "../../api/queries";
import { errorMessage, tr } from "../../copy/tr";
import { docPath } from "../../app/paths";
import { Button, buttonClass } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Icon } from "../../ui/Icon";
import { Skeleton, SkeletonText } from "../../ui/Skeleton";
import { useShell } from "../../app/shellContext";
import { EmptyArt } from "./EmptyArt";
import { LibraryPane } from "./LibraryPane";
import { useUploads } from "./uploadContext";
import s from "./HomeView.module.css";

const FEATURE_ICONS = ["computer", "info", "download"] as const;

function Welcome() {
  const { pick } = useUploads();
  return (
    <div className={s.welcome}>
      <EmptyState
        size="lg"
        headingLevel="h1"
        title={tr.home.emptyTitle}
        art={<EmptyArt />}
        actions={
          <Button variant="primary" icon="plus" onClick={pick}>
            {tr.home.emptyAction}
          </Button>
        }
        hint={tr.home.emptyHint}
      >
        <p>{tr.home.emptyBody}</p>
      </EmptyState>
      <ul className={s.features}>
        {tr.home.features.map((feature, i) => (
          <li key={feature.title} className={s.feature}>
            <span className={s.featureIcon} aria-hidden="true">
              <Icon name={FEATURE_ICONS[i]} size={16} />
            </span>
            <span>
              <strong className={s.featureTitle}>{feature.title}</strong>
              <span className={s.featureBody}>{feature.body}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HomeView() {
  const docs = useDocuments();
  const { compact, openSettings } = useShell();

  if (docs.isPending) {
    return (
      <div className={s.center} aria-busy="true">
        <div className={s.loading}>
          <Skeleton width={56} height={56} radius={12} />
          <Skeleton width="60%" height={20} />
          <SkeletonText lines={3} />
        </div>
      </div>
    );
  }

  if (docs.isError && !docs.data) {
    return (
      <div className={s.center}>
        <EmptyState
          size="lg"
          headingLevel="h1"
          icon="alert"
          tone="danger"
          title={tr.library.loadError}
          actions={
            <Button icon="refresh" onClick={() => void docs.refetch()}>
              {tr.common.retry}
            </Button>
          }
        >
          <p>{errorMessage(docs.error instanceof ApiError ? docs.error.code : "unknown_error")}</p>
        </EmptyState>
      </div>
    );
  }

  const list = docs.data ?? [];
  // Without the side library (tablet, phone) the home screen is the document list itself.
  if (compact && list.length) return <LibraryPane inline onOpenSettings={openSettings} />;
  if (!list.length) {
    return (
      <div className={s.center}>
        <Welcome />
      </div>
    );
  }

  const review = list.filter((d) => d.status === "needs_review");
  const approved = list.filter((d) => d.status === "approved").length;
  const processing = list.filter((d) => isProcessing(d.status)).length;
  const next = [...review].sort((a, b) => a.created_at.localeCompare(b.created_at))[0];

  return (
    <div className={s.center}>
      <EmptyState
        size="lg"
        headingLevel="h1"
        icon="file"
        title={tr.home.selectTitle}
        actions={
          next ? (
            <Link to={docPath(next.id)} className={buttonClass("primary")}>
              {tr.home.openFirstReview}
              <Icon name="arrowRight" size={16} />
            </Link>
          ) : null
        }
      >
        <p>{tr.home.selectBody}</p>
        <dl className={s.stats}>
          {[
            { key: "review", count: review.length, dot: s.dotReview },
            { key: "approved", count: approved, dot: s.dotOk },
            { key: "processing", count: processing, dot: s.dotRun },
          ].map((stat) => (
            <div key={stat.key} className={s.stat}>
              <dt className={s.statLabel}>
                <span className={stat.dot} aria-hidden="true" />
                {tr.library.filters[stat.key as "review" | "approved" | "processing"]}
              </dt>
              <dd className={s.statValue}>{stat.count}</dd>
            </div>
          ))}
        </dl>
      </EmptyState>
    </div>
  );
}
