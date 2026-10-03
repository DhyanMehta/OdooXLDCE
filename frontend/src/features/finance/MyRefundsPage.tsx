import { Link, useSearchParams } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";

export function MyRefundsPage() {
  const { me, activeClub } = useAuth();
  const [params] = useSearchParams();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;

  const refundsRes = useAsyncResource(
    me && clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/refunds/mine", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "refunds-mine")] : [] },
  );

  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/my-refunds">log in</Link>.
      </Feedback>
    );
  }
  if (!clubId) {
    return (
      <Feedback tone="warn">
        Select a club or open from <Link to="/orders">orders</Link>.
      </Feedback>
    );
  }

  const refunds = refundsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>My refund requests</h1>
        <p className="muted">
          Status only — refunds are paid manually by club staff outside CampusOS.
        </p>
      </div>
      <PageState
        loading={refundsRes.loading}
        error={refundsRes.error}
        empty={refunds.length === 0}
        emptyMessage="No refund requests for this club."
      >
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Requested</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Order</th>
              </tr>
            </thead>
            <tbody>
              {refunds.map((ref) => (
                <tr key={ref.id}>
                  <td>{new Date(ref.requested_at).toLocaleString()}</td>
                  <td>
                    ₹{ref.amount} {ref.currency}
                  </td>
                  <td>
                    <span className={statusBadgeClass(ref.status)}>{ref.status}</span>
                  </td>
                  <td className="muted small">{ref.reason}</td>
                  <td>
                    <Link to={`/orders/${ref.order_id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </PageState>
    </div>
  );
}
