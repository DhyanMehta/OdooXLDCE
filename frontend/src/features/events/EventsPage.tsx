import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useClubId } from "../../hooks/useClubId";
import { api, ApiError } from "../../services/api";
import type { EventItem } from "../../types/api";

export function EventsPage() {
  const { clubId, clubName, loading: clubLoading } = useClubId();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!clubId) {
      setLoading(clubLoading);
      return;
    }
    let cancelled = false;
    api
      .get<EventItem[]>(`/api/v1/clubs/${clubId}/events`)
      .then((data) => {
        if (!cancelled) setEvents(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load events");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clubId, clubLoading]);

  if (clubLoading || loading) return <Spinner />;
  if (!clubId) return <Feedback tone="warn">Club unavailable.</Feedback>;
  if (error) return <Feedback tone="danger">{error}</Feedback>;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Events</h1>
        <p className="muted">{clubName}</p>
      </div>
      {events.length === 0 ? (
        <Empty>No events to show.</Empty>
      ) : (
        <div className="stack">
          {events.map((event) => (
            <article key={event.id} className="panel row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{event.title}</h2>
                <p className="muted">
                  {new Date(event.starts_at).toLocaleString()} · {event.venue}
                </p>
                <span className="badge">{event.status}</span>{" "}
                {event.seats_remaining != null && (
                  <span className="muted small">{event.seats_remaining} seats left</span>
                )}
              </div>
              <Link className="btn" to={`/events/${event.id}?club=${clubId}`}>
                Open
              </Link>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
