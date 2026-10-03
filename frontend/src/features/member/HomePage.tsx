import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { roleTitle } from "../../lib/roles";
import { api, ApiError } from "../../services/api";
import type { Membership, Ticket } from "../../types/api";

export function MemberHomePage() {
  const { me, activeClub, loading, hasPermission } = useAuth();
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);

  const isStaff = Boolean(activeClub?.permissions.length);

  useEffect(() => {
    if (!me || !activeClub) return;
    Promise.all([
      api.get<Membership[]>(`/api/v1/clubs/${activeClub.club.id}/me/memberships`),
      api.get<Ticket[]>("/api/v1/me/tickets"),
    ])
      .then(([m, t]) => {
        setMemberships(m);
        setTickets(t.filter((x) => x.club_id === activeClub.club.id));
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed to load"));
  }, [me, activeClub]);

  if (loading) return <Spinner />;
  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login">log in</Link>.
      </Feedback>
    );
  }
  if (!activeClub) {
    return (
      <Feedback tone="warn">
        No club yet. Visit the <Link to="/clubs/tech-club">club page</Link>.
      </Feedback>
    );
  }

  const active = memberships.find((m) => m.status === "active" && new Date(m.ends_at) > new Date());

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Home</h1>
        <p className="muted">
          {activeClub.club.name} · {roleTitle(activeClub.permissions)}
        </p>
      </div>

      {error && <Feedback tone="danger">{error}</Feedback>}

      {isStaff && (
        <section className="panel row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2>Admin tools</h2>
            <p className="muted">Manage this club from the sidebar.</p>
          </div>
          <Link className="btn" to="/admin">
            Open admin
          </Link>
        </section>
      )}

      {!isStaff && (
        <section className="panel stack">
          <h2>Membership</h2>
          {active ? (
            <Feedback tone="ok">
              Active until <strong>{new Date(active.ends_at).toLocaleString()}</strong>
            </Feedback>
          ) : (
            <Feedback tone="info">
              No active membership. <Link to="/memberships">View plans</Link>
            </Feedback>
          )}
        </section>
      )}

      {isStaff && active && (
        <section className="panel stack">
          <h2>Membership</h2>
          <Feedback tone="ok">
            Active until <strong>{new Date(active.ends_at).toLocaleString()}</strong>
          </Feedback>
        </section>
      )}

      <section className="panel stack">
        <h2>Your tickets</h2>
        {tickets.length === 0 ? (
          <Empty>
            No tickets yet. <Link to="/events">Browse events</Link>
          </Empty>
        ) : (
          tickets.map((t) => (
            <div key={t.id} className="row" style={{ justifyContent: "space-between" }}>
              <span>
                <strong>{t.event_title ?? "Event"}</strong> · {t.status}
              </span>
              <Link to="/tickets">Open QR</Link>
            </div>
          ))
        )}
      </section>

      {hasPermission("check_in") && (
        <section className="panel row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2>Check-in</h2>
            <p className="muted">Door scanning for events.</p>
          </div>
          <Link className="btn" to="/admin/check-in">
            Open check-in
          </Link>
        </section>
      )}
    </div>
  );
}
