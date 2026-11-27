/** datetime-local ↔ ISO helpers and status badge classes. */

export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

export function formatCountdown(expiresAt: string | null | undefined, now = Date.now()): string | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - now;
  if (!Number.isFinite(ms)) return null;
  if (ms <= 0) return "Expired";

  // Keep a live order at one second until its actual expiration time.
  const totalSeconds = Math.ceil(ms / 1000);
  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60);
    return `${hours}h ${totalMinutes % 60}m ${seconds}s`;
  }
  return `${totalMinutes}m ${seconds}s`;
}

const warningStatuses = new Set(["pending", "draft", "upcoming", "scheduled", "refund_required"]);
const dangerStatuses = new Set(["cancelled", "failed", "expired", "revoked", "ended", "none"]);

export function statusBadgeClass(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (warningStatuses.has(normalized)) return "badge badge--warn";
  if (dangerStatuses.has(normalized)) return "badge badge--danger";
  return "badge";
}

export function safeNextPath(raw: string | null): string {
  if (!raw) return "/home";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/home";
  return raw;
}
