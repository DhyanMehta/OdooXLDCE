import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { formatCountdown, statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
export function OrderPage() {
  const { orderId = "" } = useParams();
  const { me, refresh } = useAuth();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const orderRes = useAsyncResource(
    me && orderId
      ? () =>
          api.get("/api/v1/orders/{order_id}", {
            params: { path: { order_id: orderId } },
          })
      : null,
    [me?.user.id, orderId],
    { cacheKeys: orderId ? [`order:${orderId}`, "orders"] : ["orders"] },
  );

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to={`/login?next=${encodeURIComponent(`/orders/${orderId}`)}`}>log in</Link> to
        view this order.
      </Feedback>
    );
  }

  const order = orderRes.data;
  const countdown =
    order?.status === "pending" ? formatCountdown(order.expires_at, now) : null;

  async function payDemo(success: boolean) {
    setBusy(true);
    setActionError(null);
    try {
      const updated = await api.post("/api/v1/orders/{order_id}/pay/demo", {
        params: { path: { order_id: orderId } },
        body: { success },
      });
      if (updated.status === "paid") {
        await refresh();
        invalidate(
          clubKey(updated.club_id, "memberships"),
          clubKey(updated.club_id, "events"),
          "tickets",
          "orders",
          "me",
        );
      }
      await orderRes.reload();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelOrder() {
    if (!window.confirm("Cancel this pending order?")) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.post("/api/v1/orders/{order_id}/cancel", {
        params: { path: { order_id: orderId } },
      });
      invalidate("orders");
      await orderRes.reload();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (orderRes.loading && !order) return <Spinner />;
  if (orderRes.error && !order) return <Feedback tone="danger">{orderRes.error}</Feedback>;
  if (!order) return <Feedback tone="warn">Order not found.</Feedback>;

  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <div className="hero-block">
        <h1>Checkout</h1>
        <p className="muted">Order status and payment.</p>
      </div>
      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <strong>Order {order.id.slice(0, 8)}…</strong>
          <span className={statusBadgeClass(order.status)}>{order.status}</span>
        </div>
        <ul>
          {order.items.map((item) => (
            <li key={item.id}>
              {item.title_snapshot} × {item.quantity} — ₹{item.unit_price_snapshot}
            </li>
          ))}
        </ul>
        <p>
          Total:{" "}
          <strong>
            ₹{order.total_amount} {order.currency}
          </strong>
        </p>
        {order.status === "pending" && countdown && (
          <p className={`countdown ${countdown === "Expired" ? "countdown--expired" : ""}`}>
            Reservation {countdown === "Expired" ? "expired" : `expires in ${countdown}`}
          </p>
        )}
        {order.expires_at && order.status === "pending" && (
          <p className="muted small">
            Absolute expiry: {new Date(order.expires_at).toLocaleString()}
          </p>
        )}
        {order.payments[0] && (
          <p className="muted small">
            Payment: {order.payments[0].method} /{" "}
            <span className={statusBadgeClass(order.payments[0].status)}>
              {order.payments[0].status}
            </span>
            {order.payments[0].method === "demo" ? " (simulated)" : ""}
          </p>
        )}
        {(actionError || orderRes.error) && (
          <Feedback tone="danger">{actionError ?? orderRes.error}</Feedback>
        )}
        {order.status === "pending" && (
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => void payDemo(true)}>
              {busy ? "Processing…" : "Pay with demo adapter"}
            </button>
            <button className="btn btn--ghost" disabled={busy} onClick={() => void payDemo(false)}>
              Simulate failure
            </button>
            <button className="btn btn--danger" disabled={busy} onClick={() => void cancelOrder()}>
              Cancel order
            </button>
          </div>
        )}
        {order.status === "paid" && (
          <Feedback tone="ok">
            Payment confirmed. <Link to="/home">Home</Link> · <Link to="/tickets">My tickets</Link> ·{" "}
            <Link to="/orders">All orders</Link>
          </Feedback>
        )}
        {order.status === "cancelled" && (
          <Feedback tone="warn">This order was cancelled.</Feedback>
        )}
        {order.status === "failed" && (
          <Feedback tone="danger">Payment failed. You can start a new purchase.</Feedback>
        )}
        {order.status === "refund_required" && (
          <Feedback tone="warn">
            Payment recorded but fulfillment could not complete. Refund required — not
            auto-completed.
          </Feedback>
        )}
      </section>
    </div>
  );
}
