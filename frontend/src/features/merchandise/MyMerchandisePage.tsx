import { Link } from "react-router-dom";
import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { api } from "../../services/api";

export function MyMerchandisePage() {
  const { me, activeClub } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const merchRes = useAsyncResource(
    me
      ? () =>
          api.get("/api/v1/me/merchandise", {
            params: { query: clubId ? { club_id: clubId } : {} },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: ["my-merchandise"] },
  );

  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/my-merch">log in</Link>.
      </Feedback>
    );

  }
  const items = merchRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>My merchandise</h1>
        <p className="muted">
          {activeClub
            ? `Showing purchases for ${activeClub.club.name}. Switch club in the sidebar to filter.`
            : "All clubs — select a club in the sidebar to filter."}
        </p>
      </div>
      <PageState
        loading={merchRes.loading}
        error={merchRes.error}
        empty={items.length === 0}
        emptyMessage="No merchandise purchases yet."
      >
        <section className="panel stack">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Qty</th>
                <th>Fulfillment</th>
                <th>Order</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td>{row.title_snapshot}</td>
                  <td>{row.quantity}</td>
                  <td>
                    <span className={statusBadgeClass(row.fulfillment_status ?? "pending")}>
                      {row.fulfillment_status ?? "—"}
                    </span>
                  </td>
                  <td>
                    <Link to={`/orders/${row.order_id}`}>Order</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </PageState>
      {activeClub && (
        <Link className="btn btn--ghost" to={`/shop?club=${activeClub.club.id}`}>
          Back to shop
        </Link>
      )}
    </div>
  );
}
