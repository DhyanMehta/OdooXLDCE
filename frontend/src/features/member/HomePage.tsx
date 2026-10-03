import { useEffect } from "react";
import { Link } from "react-router-dom";

import { Empty, Feedback, PageState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { clubKey } from "../../lib/queryCache";
import { roleTitle } from "../../lib/roles";
import { api } from "../../services/api";
export function MemberHomePage() {
  const { me, activeClub, loading, hasPermission, refresh } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const isStaff = Boolean(activeClub?.permissions.length);

  const membershipsRes = useAsyncResource(
    me && clubId
      ? () =>
          api.get("/api/v1/clubs/{club_id}/me/memberships", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [me?.user.id, clubId],
    { cacheKeys: clubId ? [clubKey(clubId, "memberships"), "me"] : ["me"] },
  );

  const ticketsRes = useAsyncResource(
    me ? () => api.get("/api/v1/me/tickets") : null,
    [me?.user.id],
    { cacheKeys: ["tickets"] },
  );

  useEffect(() => {
    function onFocus() {
      void refresh();
      void membershipsRes.reload();
      void ticketsRes.reload();
    }
    function onVisibility() {
      if (document.visibilityState === "visible") onFocus();
    }
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh, membershipsRes.reload, ticketsRes.reload]);

  if (loading) return <Spinner />;
  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/home">log in</Link>.
      </Feedback>
    );
  }
  if (!activeClub) {
    return (
      <Feedback tone="warn">
        No club affiliation yet. Browse <Link to="/clubs">clubs</Link> and join one.
      </Feedback>
    );
  }

  const memberships = membershipsRes.data ?? [];
  const tickets = (ticketsRes.data ?? []).filter((t) => t.club_id === activeClub.club.id);
  const activePaid = memberships.find((m) => m.effective_state === "active");

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Home</h1>
        <p className="muted">
          {activeClub.club.name} · {roleTitle(activeClub.permissions)}
        </p>
      </div>

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

      <section className="panel stack">
        <h2>Club status</h2>
        <div className="row">
          {activeClub.is_member ? (
            <span className="badge">Affiliated</span>
          ) : (
            <span className="badge badge--warn">Not affiliated</span>
          )}
          {activeClub.has_active_membership || activePaid ? (
            <span className="badge">Paid membership active</span>
          ) : (
            <span className="badge badge--warn">No paid membership</span>
          )}
        </div>
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
                  <td>{m.plan_name ?? "Plan"}</td>
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
        {!isStaff && !activePaid && (
          <Feedback tone="info">
            <Link to={`/memberships?club=${activeClub.club.id}`}>View membership plans</Link>
          </Feedback>
        )}
      </section>

      <section className="panel stack">
        <h2>Your tickets</h2>
        <PageState
          loading={ticketsRes.loading}
          error={ticketsRes.error}
          empty={tickets.length === 0}
          emptyMessage="No tickets yet for this club."
        >
          {tickets.map((t) => (
            <div key={t.id} className="row" style={{ justifyContent: "space-between" }}>
              <span>
                <strong>{t.event_title ?? "Event"}</strong> ·{" "}
                <span className={statusBadgeClass(t.status)}>{t.status}</span>
              </span>
              <Link to="/tickets">Open QR</Link>
            </div>
          ))}
        </PageState>
        {tickets.length === 0 && !ticketsRes.loading && (
          <Empty>
            Browse <Link to={`/events?club=${activeClub.club.id}`}>events</Link>
          </Empty>
        )}
      </section>

      {hasPermission("check_in") && (
        <section className="panel row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2>Check-in</h2>
            <p className="muted">Confirm attendee tickets at the door.</p>
          </div>
          <Link className="btn" to="/admin/check-in">
            Open check-in
          </Link>
        </section>
      )}

      <section className="panel stack">
        <h2>Quick links</h2>
        <div className="row">
          <Link className="btn btn--ghost" to={`/shop?club=${activeClub.club.id}`}>
            Shop
          </Link>
          <Link className="btn btn--ghost" to={`/projects?club=${activeClub.club.id}`}>
            Projects
          </Link>
          <Link className="btn btn--ghost" to="/my-merch">
            My merch
          </Link>
          <Link className="btn btn--ghost" to="/my-assignments">
            My volunteering
          </Link>
          <Link className="btn btn--ghost" to={`/expenses?club=${activeClub.club.id}`}>
            Expenses
          </Link>
        </div>
      </section>
    </div>
  );
}
