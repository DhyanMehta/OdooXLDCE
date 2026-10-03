import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { EventItem, Order } from "../../types/api";

export function EventDetailPage() {
  const { eventId = "" } = useParams();
  const [params] = useSearchParams();
  const { me, activeClub, hasPermission } = useAuth();
  const clubId = params.get("club") ?? activeClub?.club.id ?? "";
  const navigate = useNavigate();
  const [event, setEvent] = useState<EventItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attendance, setAttendance] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!clubId) return;
    api
      .get<EventItem>(`/api/v1/clubs/${clubId}/events/${eventId}`)
      .then(setEvent)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed to load"));
  }, [clubId, eventId]);

  const memberPrice = useMemo(
    () => event?.ticket_types[0]?.prices.find((p) => p.audience === "member"),
    [event],
  );
  const publicPrice = useMemo(
    () => event?.ticket_types[0]?.prices.find((p) => p.audience === "public"),
    [event],
  );

  async function buy(priceId: string) {
    if (!me) {
      navigate("/login");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const order = await api.post<Order>(`/api/v1/clubs/${clubId}/orders/tickets`, {
        ticket_price_id: priceId,
        quantity: 1,
      });
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Booking failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadAttendance() {
    try {
      setAttendance(await api.get(`/api/v1/clubs/${clubId}/events/${eventId}/attendance`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Attendance unavailable");
    }
  }

  if (!clubId) return <Feedback tone="warn">Missing club context.</Feedback>;
  if (!event && !error) return <Spinner />;
  if (error && !event) return <Feedback tone="danger">{error}</Feedback>;
  if (!event) return null;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>{event.title}</h1>
        <p className="muted">{event.description}</p>
      </div>
      <section className="panel stack">
        <p>
          <strong>When:</strong> {new Date(event.starts_at).toLocaleString()} –{" "}
          {new Date(event.ends_at).toLocaleString()}
        </p>
        <p>
          <strong>Venue:</strong> {event.venue}
        </p>
        <p>
          <strong>Availability:</strong> {event.seats_remaining ?? "—"} / {event.capacity}
        </p>
        <p className="muted">
          Member price ₹{memberPrice?.amount ?? "—"} · Public price ₹{publicPrice?.amount ?? "—"}
        </p>
        {activeClub?.has_active_membership ? (
          <Feedback tone="ok">Member pricing available on your account.</Feedback>
        ) : me && !(activeClub?.permissions.length) ? (
          <Feedback tone="info">
            Public pricing applies. <Link to="/memberships">Get membership</Link> for the discount.
          </Feedback>
        ) : null}
        {error && <Feedback tone="danger">{error}</Feedback>}
        <div className="row">
          {memberPrice && (
            <button className="btn" disabled={busy} onClick={() => void buy(memberPrice.id)}>
              Book member ticket
            </button>
          )}
          {publicPrice && (
            <button className="btn btn--ghost" disabled={busy} onClick={() => void buy(publicPrice.id)}>
              Book public ticket
            </button>
          )}
        </div>
        {hasPermission("view_attendance") && (
          <div className="stack">
            <button className="btn btn--ghost" onClick={() => void loadAttendance()}>
              Load attendance report
            </button>
            {attendance && (
              <div className="panel stack">
                <p>Tickets issued: <strong>{String(attendance.tickets_issued)}</strong></p>
                <p>Check-ins: <strong>{String(attendance.unique_checkins)}</strong></p>
                <p>
                  Attendance: <strong>{String(attendance.attendance_percentage)}%</strong>
                  <span className="muted small"> (of tickets issued)</span>
                </p>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
