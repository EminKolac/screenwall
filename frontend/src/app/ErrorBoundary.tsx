import { Component, type ErrorInfo, type ReactNode } from "react";
import { tr } from "../copy/tr";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";

interface State {
  failed: boolean;
}

/** Keeps a crash in one screen from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Screen crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div style={{ margin: "auto" }}>
        <EmptyState
          title={tr.app.crashTitle}
          icon="alert"
          tone="danger"
          headingLevel="h1"
          actions={
            <Button variant="primary" icon="refresh" onClick={() => window.location.reload()}>
              {tr.app.reload}
            </Button>
          }
        >
          {tr.app.crashBody}
        </EmptyState>
      </div>
    );
  }
}
