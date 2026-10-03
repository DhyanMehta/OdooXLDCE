import type { BackendStatus } from "../../types/health";

const LABELS: Record<BackendStatus, string> = {
  loading: "Checking API…",
  connected: "API connected",
  unavailable: "API unavailable",
};

type StatusBadgeProps = {
  status: BackendStatus;
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${status}`} role="status">
      <span className="status-badge__dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  );
}
