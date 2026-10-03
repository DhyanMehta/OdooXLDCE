import type { ReactNode } from "react";

type Props = {
  tone?: "info" | "ok" | "warn" | "danger";
  children: ReactNode;
};

export function Feedback({ tone = "info", children }: Props) {
  return <div className={`feedback feedback--${tone}`}>{children}</div>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return <p className="muted">{label}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
