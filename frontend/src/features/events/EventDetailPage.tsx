import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { Attendance } from "../../types/api";

export function EventDetailPage() {
  const { eventId = "" } = useParams();
  const [params] = useSearchParams();
  const { me, clubContext, hasPermissionForClub } = useAuth();
  const clubId = params.get("club");
  const navigate = useNavigate();

  const [ticketTypeId, setTicketTypeId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attendance, setAttendance] = useState<Attendance | null>(null);

  const eventRes = useAsyncResource(
    clubId && eventId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events/{event_id}", {
            params: { path: { club_id: clubId, event_id: eventId } },
          })
      : null,
    [clubId, eventId],
    { cacheKeys: clubId ? [clubKey(clubId, "events"), `event:${eventId}`] : [] },
  );

  const event = eventRes.data;
  const resolvedClubId = clubId ?? event?.club_id ?? null;
  const ctx = resolvedClubId ? clubContext(resolvedClubId) : null;
  const hasMemberPricing = Boolean(ctx?.has_active_membership);

  const activeTypes = useMemo(
    () => (event?.ticket_types ?? []).filter((t) => t.is_active !== false),
    [event],
  );

  const selectedType =
    activeTypes.find((t) => t.id === ticketTypeId) ?? activeTypes[0] ?? null;

  const availablePrices = useMemo(() => {
    if (!selectedType) return [];
    return selectedType.prices.filter((p) => {
      if (!p.is_active) return false;
      if (p.audience === "member") return hasMemberPricing;
      return true;
    });
  }, [selectedType, hasMemberPricing]);

  const [priceId, setPriceId] = useState("");
  const selectedPrice =
    availablePrices.find((p) => p.id === priceId) ?? availablePrices[0] ?? null;

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Missing club context. Open this event from the{" "}
        <Link to="/events">events list</Link> (include <code>?club=</code>).
      </Feedback>
    );
  }

  async function buy() {
    if (!selectedPrice || !resolvedClubId) return;
    if (!me) {
      navigate(
        `/login?next=${encodeURIComponent(`/events/${eventId}?club=${resolvedClubId}`)}`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const order = await api.post("/api/v1/clubs/{club_id}/orders/tickets", {
        params: { path: { club_id: resolvedClubId } },
        body: {
          ticket_price_id: selectedPrice.id,
          quantity,
        },
      });
      invalidate(clubKey(resolvedClubId, "events"), "orders");
      navigate(`/orders/${order.id}`);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadAttendance() {
    if (!resolvedClubId) return;
    try {
      setAttendance(
        await api.get("/api/v1/clubs/{club_id}/events/{event_id}/attendance", {
          params: { path: { club_id: resolvedClubId, event_id: eventId } },
        }),
      );
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  if (eventRes.loading && !event) return <Spinner />;
  if (eventRes.error && !event) return <Feedback tone="danger">{eventRes.error}</Feedback>;
  if (!event) return <Feedback tone="warn">Event not found.</Feedback>;

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

        {hasMemberPricing ? (
          <Feedback tone="ok">Member pricing is available on your account for this club.</Feedback>
        ) : me ? (
          <Feedback tone="info">
            Public pricing applies.{" "}
            <Link to={`/memberships?club=${event.club_id}`}>Get membership</Link> for the discount.
          </Feedback>
        ) : null}

        {event.status === "published" && activeTypes.length > 0 && (
          <div className="form">
            <label>
              Ticket type
              <select
                value={selectedType?.id ?? ""}
                onChange={(e) => {
                  setTicketTypeId(e.target.value);
                  setPriceId("");
                }}
              >
                {activeTypes.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Price
              <select
                value={selectedPrice?.id ?? ""}
                onChange={(e) => setPriceId(e.target.value)}
              >
                {availablePrices.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.audience} — ₹{p.amount}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Quantity
              <input
                type="number"
                min={1}
                max={20}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
              />
            </label>
            <button
              className="btn"
              type="button"
              disabled={busy || !selectedPrice}
              onClick={() => void buy()}
            >
              {busy ? "Starting…" : "Purchase tickets"}
            </button>
          </div>
        )}

        {(error || eventRes.error) && (
          <Feedback tone="danger">{error ?? eventRes.error}</Feedback>
        )}

        {resolvedClubId && hasPermissionForClub(resolvedClubId, "view_attendance") && (
          <div className="stack">
            <button className="btn btn--ghost" type="button" onClick={() => void loadAttendance()}>
              Load attendance report
            </button>
            {attendance && (
              <div className="panel stack">
                <p>
                  Tickets issued: <strong>{String(attendance.tickets_issued)}</strong>
                </p>
                <p>
                  Check-ins: <strong>{String(attendance.unique_checkins)}</strong>
                </p>
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
