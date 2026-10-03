import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { api, ApiError } from "../../services/api";
import type { Announcement, ClubContext, EventItem, Plan } from "../../types/api";

export function ClubPage() {
  const { slug = "tech-club" } = useParams();
  const [ctx, setCtx] = useState<ClubContext | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const clubCtx = await api.get<ClubContext>(`/api/v1/clubs/by-slug/${slug}`);
        const [ev, an, pl] = await Promise.all([
          api.get<EventItem[]>(`/api/v1/clubs/${clubCtx.club.id}/events`),
          api.get<Announcement[]>(`/api/v1/clubs/${clubCtx.club.id}/announcements`),
          api.get<Plan[]>(`/api/v1/clubs/${clubCtx.club.id}/plans`),
        ]);
        if (!cancelled) {
          setCtx(clubCtx);
          setEvents(ev.filter((e) => e.status === "published"));
          setAnnouncements(an.filter((a) => a.status === "published"));
          setPlans(pl);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Failed to load club");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  async function subscribe(e: FormEvent) {
    e.preventDefault();
    if (!ctx) return;
    setMessage(null);
    try {
      const res = await api.post<{ message: string }>(
        `/api/v1/clubs/${ctx.club.id}/mailing-list/subscribe`,
        { email },
      );
      setMessage(res.message);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Subscribe failed");
    }
  }

  if (loading) return <Spinner />;
  if (error || !ctx) return <Feedback tone="danger">{error ?? "Club unavailable"}</Feedback>;

  return (
    <div className="stack">
      <section className="hero-block">
        <h1>{ctx.club.name}</h1>
        <p className="muted">{ctx.club.description}</p>
        {ctx.has_active_membership && <span className="badge">Active member</span>}
      </section>

      <section className="panel stack">
        <h2>Upcoming events</h2>
        {events.length === 0 ? (
          <Empty>No published events yet.</Empty>
        ) : (
          events.map((event) => (
            <div key={event.id} className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong>{event.title}</strong>
                <div className="muted small">{new Date(event.starts_at).toLocaleString()} · {event.venue}</div>
              </div>
              <Link className="btn btn--ghost" to={`/events/${event.id}?club=${ctx.club.id}`}>
                Details
              </Link>
            </div>
          ))
        )}
      </section>

      <section className="grid-2">
        <div className="panel stack">
          <h2>Public announcements</h2>
          {announcements.filter((a) => a.visibility === "public").length === 0 ? (
            <Empty>No public announcements.</Empty>
          ) : (
            announcements
              .filter((a) => a.visibility === "public")
              .map((a) => (
                <div key={a.id}>
                  <strong>{a.title}</strong>
                  <p className="muted">{a.body}</p>
                </div>
              ))
          )}
        </div>
        <div className="panel stack">
          <h2>Membership</h2>
          <p className="muted">Member benefit in this version: discounted event ticket prices.</p>
          {plans.map((p) => (
            <div key={p.id}>
              <strong>{p.name}</strong> — ₹{p.dues_amount}
              <div className="muted small">{p.description}</div>
            </div>
          ))}
          <Link className="btn" to="/memberships">
            View plans / buy
          </Link>
        </div>
      </section>

      <section className="panel stack">
        <h2>Mailing list</h2>
        <p className="muted">Get club updates by email.</p>
        <form className="form" onSubmit={subscribe}>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <button className="btn" type="submit">
            Subscribe
          </button>
        </form>
        {message && <Feedback tone="ok">{message}</Feedback>}
      </section>
    </div>
  );
}
