import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { api, ApiError } from "../../services/api";
import type { Order } from "../../types/api";

export function OrderPage() {
  const { orderId = "" } = useParams();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      setOrder(await api.get<Order>(`/api/v1/orders/${orderId}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load order");
    }
  }

  useEffect(() => {
    void load();
  }, [orderId]);

  async function payDemo(success: boolean) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.post<Order>(`/api/v1/orders/${orderId}/pay/demo`, { success });
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Payment failed");
    } finally {
      setBusy(false);
    }
  }

  if (!order && !error) return <Spinner />;
  if (error && !order) return <Feedback tone="danger">{error}</Feedback>;
  if (!order) return null;

  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <div className="hero-block">
        <h1>Checkout</h1>
        <p className="muted">Development payment (simulated).</p>
      </div>
      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <strong>Order {order.id.slice(0, 8)}…</strong>
          <span className={`badge ${order.status === "paid" ? "" : "badge--warn"}`}>{order.status}</span>
        </div>
        <ul>
          {order.items.map((item) => (
            <li key={item.id}>
              {item.title_snapshot} × {item.quantity} — ₹{item.unit_price_snapshot}
            </li>
          ))}
        </ul>
        <p>
          Total: <strong>₹{order.total_amount} {order.currency}</strong>
        </p>
        {order.expires_at && (
          <p className="muted small">Reservation expires {new Date(order.expires_at).toLocaleString()}</p>
        )}
        {order.payments[0] && (
          <p className="muted small">
            Payment: {order.payments[0].method} / {order.payments[0].status}
            {order.payments[0].method === "demo" ? " (simulated)" : ""}
          </p>
        )}
        {error && <Feedback tone="danger">{error}</Feedback>}
        {order.status === "pending" && (
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => void payDemo(true)}>
              {busy ? "Processing…" : "Pay with demo adapter (success)"}
            </button>
            <button className="btn btn--ghost" disabled={busy} onClick={() => void payDemo(false)}>
              Simulate failure
            </button>
          </div>
        )}
        {order.status === "paid" && (
          <Feedback tone="ok">
            Payment confirmed.{" "}
            <Link to="/home">View membership/tickets</Link> · <Link to="/tickets">My tickets</Link>
          </Feedback>
        )}
        {order.status === "refund_required" && (
          <Feedback tone="warn">
            Payment recorded but capacity was unavailable after reservation expiry. Refund required — not auto-completed.
          </Feedback>
        )}
      </section>
    </div>
  );
}
