import { useState } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { Order } from "../../types/api";

export function AdminDuesPage() {
  const { activeClub, hasPermission, me, refresh } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Order | null>(null);

  const duesRes = useAsyncResource(
    clubId && hasPermission("confirm_dues")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/pending-dues", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, hasPermission("confirm_dues")],
    { cacheKeys: clubId ? [clubKey(clubId, "pending-dues")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("confirm_dues")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function confirm(orderId: string) {
    const providerRef = (refs[orderId] ?? "").trim();
    if (!providerRef) {
      setError("Provider reference is required.");
      return;
    }
    setBusyId(orderId);
    setError(null);
    try {
      const updated = await api.post("/api/v1/orders/{order_id}/pay/manual", {
        params: { path: { order_id: orderId } },
        body: { provider_ref: providerRef },
      });
      setConfirmed(updated);
      invalidate(
        clubKey(activeClub!.club.id, "pending-dues"),
        clubKey(activeClub!.club.id, "memberships"),
        clubKey(activeClub!.club.id, "members"),
        "orders",
        "me",
      );
      await refresh();
      await duesRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  const rows = duesRes.data ?? [];
  const payment = confirmed?.payments.find((p) => p.status === "confirmed") ?? confirmed?.payments[0];
  const actorLabel =
    payment?.confirmed_by_user_id && me?.user.id === payment.confirmed_by_user_id
      ? me.user.full_name
      : payment?.confirmed_by_user_id
        ? `User ${payment.confirmed_by_user_id.slice(0, 8)}`
        : null;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Pending dues</h1>
        <p className="muted">Manually confirm offline membership payments.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {confirmed && payment && (
        <Feedback tone="ok">
          Confirmed order {confirmed.id.slice(0, 8)}… · ref {payment.provider_ref ?? "—"} · actor{" "}
          {actorLabel ?? "—"} ·{" "}
          {payment.confirmed_at
            ? new Date(payment.confirmed_at).toLocaleString()
            : "timestamp unavailable"}
        </Feedback>
      )}

      <PageState
        loading={duesRes.loading}
        error={duesRes.error}
        empty={rows.length === 0}
        emptyMessage="No pending dues."
      >
        <section className="stack">
          {rows.map((order) => (
            <article key={order.id} className="panel stack">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>{order.buyer_name ?? "Member"}</strong>
                  <div className="muted small">{order.buyer_email}</div>
                </div>
                <span className={statusBadgeClass(order.status)}>{order.status}</span>
              </div>
              <ul>
                {order.items.map((item) => (
                  <li key={item.id}>
                    {item.title_snapshot} — ₹{item.unit_price_snapshot}
                  </li>
                ))}
              </ul>
              <p>
                Total <strong>₹{order.total_amount}</strong> · created{" "}
                {new Date(order.created_at).toLocaleString()}
              </p>
              <label>
                Provider reference
                <input
                  value={refs[order.id] ?? ""}
                  onChange={(e) => setRefs((prev) => ({ ...prev, [order.id]: e.target.value }))}
                  placeholder="Receipt / UPI / cash slip id"
                  required
                />
              </label>
              <button
                className="btn"
                type="button"
                disabled={busyId === order.id}
                onClick={() => void confirm(order.id)}
              >
                {busyId === order.id ? "Confirming…" : "Confirm payment"}
              </button>
            </article>
          ))}
        </section>
      </PageState>
    </div>
  );
}
