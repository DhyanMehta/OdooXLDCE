import { Link, useSearchParams } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";
export function EventsPage() {
  const { activeClub, me } = useAuth();
  const [params] = useSearchParams();
  const clubId = params.get("club") ?? activeClub?.club.id ?? null;
  const clubName =
    activeClub?.club.id === clubId
      ? activeClub.club.name
      : me?.clubs.find((c) => c.club.id === clubId)?.club.name;

  const eventsRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "events")] : [] },
  );

  if (!clubId) {
    return (
      <Feedback tone="warn">
        Pick a club to browse events from the <Link to="/clubs">clubs directory</Link>, or select an
        active club in the sidebar.
      </Feedback>
    );
  }

  const events = eventsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Events</h1>
        <p className="muted">{clubName ?? "Club events"}</p>
      </div>
      <PageState
        loading={eventsRes.loading}
        error={eventsRes.error}
        empty={events.length === 0}
        emptyMessage="No events to show."
      >
        <div className="stack">
          {events.map((event) => (
            <article key={event.id} className="panel row" style={{ justifyContent: "space-between" }}>
              <div>
                <h2>{event.title}</h2>
                <p className="muted">
                  {new Date(event.starts_at).toLocaleString()} · {event.venue}
                </p>
                <span className={statusBadgeClass(event.status)}>{event.status}</span>{" "}
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
      </PageState>
    </div>
  );
}
