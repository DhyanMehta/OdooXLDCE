import { useState } from "react";
import { Link } from "react-router-dom";

import { Feedback, PageState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
const PAGE_SIZE = 20;

export function OrdersPage() {
  const { me, loading: authLoading } = useAuth();
  const [offset, setOffset] = useState(0);
  const [refundBusyId, setRefundBusyId] = useState<string | null>(null);
  const [refundError, setRefundError] = useState<string | null>(null);

  const ordersRes = useAsyncResource(
    me
      ? () =>
          api.get("/api/v1/me/orders", {
            params: { query: { limit: PAGE_SIZE, offset } },
          })
      : null,
    [me?.user.id, offset],
    { cacheKeys: ["orders"] },
  );

  if (authLoading) return <Spinner />;
  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/orders">log in</Link> to view orders.
      </Feedback>
    );
  }

  const page = ordersRes.data;
  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  async function requestRefund(orderId: string, clubId: string) {
    const reason = window.prompt("Reason for refund request (optional):") ?? "";
    setRefundBusyId(orderId);
    setRefundError(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/refunds", {
        params: { path: { club_id: clubId } },
        body: { order_id: orderId, reason },
      });
      invalidate(clubKey(clubId, "refunds-mine"), "orders");
    } catch (err) {
      setRefundError(formatApiError(err));
    } finally {
      setRefundBusyId(null);
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Orders</h1>
        <p className="muted">Your membership and ticket checkouts.</p>
      </div>
      {refundError && <Feedback tone="danger">{refundError}</Feedback>}
      <PageState
        loading={ordersRes.loading}
        error={ordersRes.error}
        empty={items.length === 0}
        emptyMessage="No orders yet."
      >
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Created</th>
                <th>Status</th>
                <th>Total</th>
                <th>Items</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((order) => (
                <tr key={order.id}>
                  <td>{new Date(order.created_at).toLocaleString()}</td>
                  <td>
                    <span className={statusBadgeClass(order.status)}>{order.status}</span>
                  </td>
                  <td>
                    ₹{order.total_amount} {order.currency}
                  </td>
                  <td className="muted small">
                    {order.items.map((i) => i.title_snapshot).join(", ") || "—"}
                  </td>
                  <td>
                    <Link to={`/orders/${order.id}`}>Open</Link>
                  </td>
                  <td>
                    {(order.status === "paid" || order.status === "refund_required") && (
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={refundBusyId === order.id}
                        onClick={() => void requestRefund(order.id, order.club_id)}
                      >
                        {refundBusyId === order.id ? "…" : "Request refund"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <div className="pagination">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!canPrev || ordersRes.loading}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            Previous
          </button>
          <span className="muted small">
            {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`} of {total}
          </span>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!canNext || ordersRes.loading}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </PageState>
    </div>
  );
}
