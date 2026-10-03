import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useClubId } from "../../hooks/useClubId";
import { api, ApiError } from "../../services/api";
import type { Membership, Order, Plan } from "../../types/api";

export function MembershipsPage() {
  const { me } = useAuth();
  const { clubId, loading: clubLoading } = useClubId();
  const navigate = useNavigate();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!clubId) {
      setLoading(clubLoading);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const p = await api.get<Plan[]>(`/api/v1/clubs/${clubId}/plans`);
        let m: Membership[] = [];
        if (me) m = await api.get<Membership[]>(`/api/v1/clubs/${clubId}/me/memberships`);
        if (!cancelled) {
          setPlans(p);
          setMemberships(m);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [clubId, clubLoading, me]);

  async function buy(planId: string) {
    if (!clubId) return;
    if (!me) {
      navigate("/login");
      return;
    }
    setBusyId(planId);
    setError(null);
    try {
      const order = await api.post<Order>(`/api/v1/clubs/${clubId}/orders/membership`, {
        plan_id: planId,
      });
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start purchase");
    } finally {
      setBusyId(null);
    }
  }

  if (clubLoading || loading) return <Spinner />;
  if (!clubId) return <Feedback tone="warn">Club unavailable.</Feedback>;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Membership plans</h1>
        <p className="muted">
          Benefit: discounted member ticket prices. Plan edits never rewrite existing entitlements.
        </p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      <div className="grid-2">
        {plans.map((plan) => (
          <article key={plan.id} className="panel stack">
            <h2>{plan.name}</h2>
            <p className="muted">{plan.description}</p>
            <p>
              <strong>₹{plan.dues_amount}</strong>{" "}
              <span className="muted small">
                {plan.duration_days ? `${plan.duration_days} days` : `until ${plan.fixed_expires_on}`}
              </span>
            </p>
            <button className="btn" disabled={busyId === plan.id} onClick={() => void buy(plan.id)}>
              {busyId === plan.id ? "Starting…" : "Purchase"}
            </button>
          </article>
        ))}
      </div>
      {plans.length === 0 && <Empty>No active plans.</Empty>}
      {me && (
        <section className="panel stack">
          <h2>Your memberships</h2>
          {memberships.length === 0 ? (
            <Empty>No membership records yet.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Starts</th>
                  <th>Ends</th>
                </tr>
              </thead>
              <tbody>
                {memberships.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <span className={`badge ${m.status === "active" ? "" : "badge--warn"}`}>{m.status}</span>
                    </td>
                    <td>{new Date(m.starts_at).toLocaleString()}</td>
                    <td>{new Date(m.ends_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Link to="/home">Member home</Link>
        </section>
      )}
    </div>
  );
}
