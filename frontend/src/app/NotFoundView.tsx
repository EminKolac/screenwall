import { Link } from "react-router-dom";
import { tr } from "../copy/tr";
import { buttonClass } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";

export function NotFoundView() {
  return (
    <div style={{ margin: "auto" }}>
      <EmptyState
        title={tr.app.notFoundTitle}
        icon="alert"
        headingLevel="h1"
        actions={
          <Link to="/" className={buttonClass("secondary")}>
            {tr.app.backHome}
          </Link>
        }
      >
        {tr.app.notFoundBody}
      </EmptyState>
    </div>
  );
}
