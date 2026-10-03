import type { ReactNode } from "react";

type Tone = "info" | "ok" | "warn" | "danger";

export function Feedback({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div className={`feedback feedback--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted loading-line" aria-busy="true" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function PageState({
  loading,
  error,
  empty,
  emptyMessage,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  if (loading) return <Spinner />;
  if (error) return <Feedback tone="danger">{error}</Feedback>;
  if (empty) return <Empty>{emptyMessage ?? "Nothing here yet."}</Empty>;
  return <>{children}</>;
}
