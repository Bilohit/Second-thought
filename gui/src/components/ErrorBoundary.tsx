/**
 * ErrorBoundary.tsx
 * -----------------
 * Zero-dependency class-based error boundary (React only exposes
 * `getDerivedStateFromError`/`componentDidCatch` on classes — no hook
 * equivalent exists). Catches render-phase throws in `children` and shows
 * either a caller-supplied `fallback` or a small default "Something went
 * wrong" card styled with the app's existing CSS vars. Does NOT catch
 * event-handler or async errors — those never reach React's boundary
 * mechanism; that's fine, the target here is render throws (C2).
 */
import { Component, type ReactNode, type ErrorInfo } from "react";
import { logger } from "../lib/logger";

interface Props {
  /** Custom recovery UI. Receives `reset` to clear the caught error and
   *  re-attempt rendering `children`. Omit for the default card. */
  fallback?: (reset: () => void) => ReactNode;
  /** Fires once per catch, in addition to this boundary's own
   *  `logger.error` call — e.g. so a caller can auto-collapse a compact
   *  panel back to the pill. */
  onError?: (error: unknown) => void;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error("ui", "Render error caught by ErrorBoundary", {
      error: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
    this.props.onError?.(error);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.reset);
      return (
        <div role="alert" aria-label="Component error" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "var(--space-2)", padding: "var(--space-3)" }}>
          <span style={{ fontSize: 12, color: "var(--text-2)" }}>Something went wrong.</span>
          <button
            type="button"
            className="btn-hover"
            onClick={this.reset}
            style={{ fontSize: 12, padding: "4px 10px", background: "var(--surface)", border: "1px solid var(--border)", color: "var(--text-1)", cursor: "pointer" }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
