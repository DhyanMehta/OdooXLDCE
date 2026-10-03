import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Empty, Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
export function MembershipsPage() {
  const { me, activeClub } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;

  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const plansRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/plans", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "plans")] : [] },
  );
  const membershipsRes = useAsyncResource(
    me && clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/me/memberships", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "memberships")] : [] },
  );

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club first from the <Link to="/clubs">clubs directory</Link>.
      </Feedback>
    );
  }

  async function buy(planId: string) {
    if (!clubId) return;
    if (!me) {
      navigate(`/login?next=${encodeURIComponent(`/memberships?club=${clubId}`)}`);
      return;
    }
    setBusyId(planId);
    setError(null);
    try {
      const order = await api.post("/api/v1/clubs/{club_id}/orders/membership", {
        params: { path: { club_id: clubId } },
        body: { plan_id: planId },
      });
      invalidate(clubKey(clubId, "memberships"), clubKey(clubId, "plans"), "orders");
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyId(null);
    }
  }

  const plans = plansRes.data ?? [];
  const memberships = membershipsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Membership plans</h1>
        <p className="muted">
          {clubName ?? "Club"} — paid membership unlocks member ticket pricing.
        </p>
      </div>
      {(error || plansRes.error) && (
        <Feedback tone="danger">{error ?? plansRes.error}</Feedback>
      )}
      <PageState
        loading={plansRes.loading}
        error={null}
        empty={plans.length === 0}
        emptyMessage="No active plans."
      >
        <div className="grid-2">
          {plans.map((plan) => (
            <article key={plan.id} className="panel stack">
              <h2>{plan.name}</h2>
              <p className="muted">{plan.description}</p>
              <p>
                <strong>₹{plan.dues_amount}</strong>{" "}
                <span className="muted small">
                  {plan.duration_days
                    ? `${plan.duration_days} days`
                    : plan.fixed_expires_on
                      ? `until ${plan.fixed_expires_on}`
                      : ""}
                </span>
              </p>
              <button
                className="btn"
                disabled={busyId === plan.id}
                onClick={() => void buy(plan.id)}
              >
                {busyId === plan.id ? "Starting…" : "Purchase"}
              </button>
            </article>
          ))}
        </div>
      </PageState>

      {me && (
        <section className="panel stack">
          <h2>Your memberships</h2>
          <PageState
            loading={membershipsRes.loading}
            error={membershipsRes.error}
            empty={memberships.length === 0}
            emptyMessage="No membership records yet."
          >
            <table>
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>State</th>
                  <th>Starts</th>
                  <th>Ends</th>
                </tr>
              </thead>
              <tbody>
                {memberships.map((m) => (
                  <tr key={m.id}>
                    <td>{m.plan_name ?? "—"}</td>
                    <td>
                      <span className={statusBadgeClass(m.effective_state ?? m.status)}>
                        {m.effective_state ?? m.status}
                      </span>
                    </td>
                    <td>{new Date(m.starts_at).toLocaleString()}</td>
                    <td>{new Date(m.ends_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </PageState>
          {memberships.length === 0 && !membershipsRes.loading && (
            <Empty>No membership records yet.</Empty>
          )}
        </section>
      )}
    </div>
  );
}
