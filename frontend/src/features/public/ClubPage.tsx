import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Empty, Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
export function ClubPage() {
  const { slug = "" } = useParams();
  const { me, refresh, setActiveClubId } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);

  const ctxRes = useAsyncResource(
    slug
      ? () =>
          api.get("/api/v1/clubs/by-slug/{slug}", {
            params: { path: { slug } },
          })
      : null,
    [slug],
    { cacheKeys: slug ? [`club-slug:${slug}`] : [] },
  );
  const clubId = ctxRes.data?.club.id ?? null;

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
  const announcementsRes = useAsyncResource(
    clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/announcements", {
            params: { path: { club_id: clubId }, query: { limit: 10, offset: 0 } },
          })
      : null,
    [clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "announcements")] : [] },
  );
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

  const ctx = ctxRes.data;
  const events = (eventsRes.data ?? []).filter((e) => e.status === "published");
  const announcements = (announcementsRes.data?.items ?? []).filter(
    (a) => a.status === "published" && a.visibility === "public",
  );
  const plans = plansRes.data ?? [];

  async function joinClub() {
    if (!ctx) return;
    if (!me) {
      navigate(`/login?next=${encodeURIComponent(`/clubs/${slug}`)}`);
      return;
    }
    setJoining(true);
    setActionError(null);
    setMessage(null);
    try {
      await api.post("/api/v1/clubs/{club_id}/join", {
        params: { path: { club_id: ctx.club.id } },
      });
      setActiveClubId(ctx.club.id);
      await refresh();
      invalidate(`club-slug:${slug}`, clubKey(ctx.club.id, "*"), "me");
      setMessage("You are now affiliated with this club.");
      await ctxRes.reload();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setJoining(false);
    }
  }

  async function subscribe(e: FormEvent) {
    e.preventDefault();
    if (!ctx) return;
    if (!consent) {
      setActionError("Consent is required to subscribe.");
      return;
    }
    setMessage(null);
    setActionError(null);
    try {
      const res = await api.post("/api/v1/clubs/{club_id}/mailing-list/subscribe", {
        params: { path: { club_id: ctx.club.id } },
        body: { email, consent: true },
      });
      setMessage(res.message);
      setEmail("");
      setConsent(false);
    } catch (err) {
      setActionError(formatApiError(err));
    }
  }

  if (!slug) {
    return (
      <Feedback tone="warn">
        Missing club. <Link to="/clubs">Browse clubs</Link>
      </Feedback>
    );
  }

  return (
    <div className="stack">
      <PageState loading={ctxRes.loading} error={ctxRes.error} empty={!ctx} emptyMessage="Club not found.">
        {ctx && (
          <>
            <section className="hero-block">
              <h1>{ctx.club.name}</h1>
              <p className="muted">{ctx.club.description}</p>
              <div className="row">
                {ctx.is_member ? (
                  <span className="badge">Affiliated</span>
                ) : (
                  <span className="badge badge--warn">Not affiliated</span>
                )}
                {ctx.has_active_membership ? (
                  <span className="badge">Paid membership active</span>
                ) : (
                  <span className="badge badge--warn">No paid membership</span>
                )}
              </div>
            </section>

            {(actionError || message) && (
              <Feedback tone={actionError ? "danger" : "ok"}>{actionError ?? message}</Feedback>
            )}

            {!ctx.is_member && (
              <section className="panel row" style={{ justifyContent: "space-between" }}>
                <div>
                  <h2>Join this club</h2>
                  <p className="muted">Affiliation is free. Paid membership is separate.</p>
                </div>
                <button className="btn" type="button" disabled={joining} onClick={() => void joinClub()}>
                  {joining ? "Joining…" : me ? "Join club" : "Log in to join"}
                </button>
              </section>
            )}

            <section className="row">
              <Link className="btn" to={`/events?club=${ctx.club.id}`}>
                Events
              </Link>
              <Link className="btn btn--ghost" to={`/memberships?club=${ctx.club.id}`}>
                Memberships
              </Link>
              <Link className="btn btn--ghost" to={`/announcements?club=${ctx.club.id}`}>
                Announcements
              </Link>
              <Link className="btn btn--ghost" to={`/shop?club=${ctx.club.id}`}>
                Shop
              </Link>
              <Link className="btn btn--ghost" to={`/projects?club=${ctx.club.id}`}>
                Projects
              </Link>
            </section>

            <section className="panel stack">
              <h2>Upcoming events</h2>
              {eventsRes.loading ? (
                <p className="muted">Loading events…</p>
              ) : events.length === 0 ? (
                <Empty>No published events yet.</Empty>
              ) : (
                events.map((event) => (
                  <div key={event.id} className="row" style={{ justifyContent: "space-between" }}>
                    <div>
                      <strong>{event.title}</strong>
                      <div className="muted small">
                        {new Date(event.starts_at).toLocaleString()} · {event.venue}
                      </div>
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
                {announcements.length === 0 ? (
                  <Empty>No public announcements.</Empty>
                ) : (
                  announcements.map((a) => (
                    <div key={a.id}>
                      <strong>
                        <Link to={`/announcements/${a.id}?club=${ctx.club.id}`}>{a.title}</Link>
                      </strong>
                      <p className="muted">{a.body.slice(0, 140)}{a.body.length > 140 ? "…" : ""}</p>
                    </div>
                  ))
                )}
              </div>
              <div className="panel stack">
                <h2>Membership</h2>
                <p className="muted">
                  Affiliation lets you join the club. Paid membership unlocks member ticket pricing.
                </p>
                {plans.map((p) => (
                  <div key={p.id}>
                    <strong>{p.name}</strong> — ₹{p.dues_amount}
                    <div className="muted small">{p.description}</div>
                  </div>
                ))}
                <Link className="btn" to={`/memberships?club=${ctx.club.id}`}>
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
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </label>
                <label className="row" style={{ alignItems: "center", gap: "0.5rem" }}>
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  <span>I agree to receive club announcement emails.</span>
                </label>
                <button className="btn" type="submit" disabled={!consent}>
                  Subscribe
                </button>
              </form>
            </section>
          </>
        )}
      </PageState>
    </div>
  );
}
