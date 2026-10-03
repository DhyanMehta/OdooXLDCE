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
  if (Number.isNaN(ms)) return null;
  if (ms <= 0) return "Expired";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return `${h}h ${rm}m ${s}s`;
  }
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function statusBadgeClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "paid" || s === "active" || s === "published" || s === "confirmed" || s === "valid") {
    return "badge";
  }
  if (
    s === "pending" ||
    s === "draft" ||
    s === "upcoming" ||
    s === "scheduled" ||
    s === "refund_required"
  ) {
    return "badge badge--warn";
  }
  if (
    s === "cancelled" ||
    s === "failed" ||
    s === "expired" ||
    s === "revoked" ||
    s === "ended" ||
    s === "none"
  ) {
    return "badge badge--danger";
  }
  return "badge";
}

export function safeNextPath(raw: string | null): string {
  if (!raw) return "/home";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/home";
  return raw;
}
