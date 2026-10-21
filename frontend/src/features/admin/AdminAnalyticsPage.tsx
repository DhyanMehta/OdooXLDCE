import { Link } from "react-router-dom";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { clubKey } from "../../lib/queryCache";
import { api } from "../../services/api";

function formatCurrency(amount: string | number): string {
  const num = typeof amount === "string" ? parseFloat(amount) : amount;
  if (isNaN(num)) return "₹0.00";
  return `₹${num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function AdminAnalyticsPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;
  const canView = hasPermission("view_finance");

  const dashboardRes = useAsyncResource(
    clubId && canView
      ? () =>
          api.get("/api/v1/clubs/{club_id}/analytics/dashboard", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, canView],
    { cacheKeys: clubId ? [clubKey(clubId, "analytics-dashboard")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!canView) {
    return (
      <Feedback tone="danger">
        Forbidden. You do not have permission to view club analytics.
      </Feedback>
    );
  }

  const data = dashboardRes.data;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Analytics · {activeClub.club.name}</h1>
        <p className="muted">
          At-a-glance club metrics: membership health, event attendance, and revenue breakdown.
        </p>
      </div>

      <PageState
        loading={dashboardRes.loading}
        error={dashboardRes.error}
      >
        {data && (
          <div className="stack">
            {/* Top Stat Cards */}
            <section className="grid-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              <div
                className="panel stack"
                style={{
                  borderLeft: "4px solid var(--accent)",
                  background: "linear-gradient(135deg, rgba(15, 107, 76, 0.05) 0%, #ffffff 100%)",
                }}
              >
                <span className="muted small" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  👥 Total Members
                </span>
                <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--ink)" }}>
                  {data.summary.total_members}
                </div>
                <span className="small muted">Affiliated club members</span>
              </div>

              <div
                className="panel stack"
                style={{
                  borderLeft: "4px solid #0f6b4c",
                  background: "linear-gradient(135deg, rgba(15, 107, 76, 0.08) 0%, #ffffff 100%)",
                }}
              >
                <span className="muted small" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  ✅ Active Memberships
                </span>
                <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--ok)" }}>
                  {data.summary.active_memberships}
                </div>
                <span className="small muted">Currently paid & valid</span>
              </div>

              <div
                className="panel stack"
                style={{
                  borderLeft: "4px solid #1d65a6",
                  background: "linear-gradient(135deg, rgba(29, 101, 166, 0.06) 0%, #ffffff 100%)",
                }}
              >
                <span className="muted small" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  📅 Upcoming Events
                </span>
                <div style={{ fontSize: "2rem", fontWeight: 700, color: "#1d65a6" }}>
                  {data.summary.upcoming_events}
                </div>
                <span className="small muted">Published scheduled events</span>
              </div>

              <div
                className="panel stack"
                style={{
                  borderLeft: "4px solid #d48806",
                  background: "linear-gradient(135deg, rgba(212, 136, 6, 0.07) 0%, #ffffff 100%)",
                }}
              >
                <span className="muted small" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  💰 Total Revenue
                </span>
                <div style={{ fontSize: "2rem", fontWeight: 700, color: "#9a5b12" }}>
                  {formatCurrency(data.summary.total_revenue)}
                </div>
                <span className="small muted">All-time paid orders</span>
              </div>
            </section>

            {/* Middle Row: Membership Health & Revenue by Type */}
            <div className="grid-2">
              {/* Membership Breakdown */}
              <section className="panel stack">
                <h2>Membership breakdown</h2>
                <p className="muted small">Distribution of member entitlement statuses.</p>

                {(() => {
                  const { active, expired, revoked } = data.membership_breakdown;
                  const total = active + expired + revoked;
                  const activePct = total > 0 ? (active / total) * 100 : 0;
                  const expiredPct = total > 0 ? (expired / total) * 100 : 0;
                  const revokedPct = total > 0 ? (revoked / total) * 100 : 0;

                  return (
                    <div className="stack" style={{ gap: "1.2rem" }}>
                      {/* Visual progress bar */}
                      <div
                        style={{
                          display: "flex",
                          height: "14px",
                          borderRadius: "7px",
                          overflow: "hidden",
                          background: "var(--line)",
                        }}
                      >
                        {total > 0 ? (
                          <>
                            {active > 0 && (
                              <div
                                title={`Active: ${active} (${activePct.toFixed(1)}%)`}
                                style={{ width: `${activePct}%`, background: "var(--ok)" }}
                              />
                            )}
                            {expired > 0 && (
                              <div
                                title={`Expired: ${expired} (${expiredPct.toFixed(1)}%)`}
                                style={{ width: `${expiredPct}%`, background: "#d48806" }}
                              />
                            )}
                            {revoked > 0 && (
                              <div
                                title={`Revoked: ${revoked} (${revokedPct.toFixed(1)}%)`}
                                style={{ width: `${revokedPct}%`, background: "var(--danger)" }}
                              />
                            )}
                          </>
                        ) : (
                          <div style={{ width: "100%", background: "var(--line)" }} />
                        )}
                      </div>

                      {/* Legend / Metrics */}
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <div className="stack" style={{ gap: "0.2rem" }}>
                          <span className="badge">Active</span>
                          <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--ok)" }}>
                            {active}
                          </span>
                          <span className="muted small">{total > 0 ? `${activePct.toFixed(1)}%` : "0%"}</span>
                        </div>

                        <div className="stack" style={{ gap: "0.2rem" }}>
                          <span className="badge badge--warn">Expired</span>
                          <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "#9a5b12" }}>
                            {expired}
                          </span>
                          <span className="muted small">{total > 0 ? `${expiredPct.toFixed(1)}%` : "0%"}</span>
                        </div>

                        <div className="stack" style={{ gap: "0.2rem" }}>
                          <span className="badge badge--danger">Revoked</span>
                          <span style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--danger)" }}>
                            {revoked}
                          </span>
                          <span className="muted small">{total > 0 ? `${revokedPct.toFixed(1)}%` : "0%"}</span>
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </section>

              {/* Revenue Breakdown */}
              <section className="panel stack">
                <h2>Revenue by category</h2>
                <p className="muted small">Income generated per item kind.</p>

                <div className="stack" style={{ gap: "0.75rem" }}>
                  {data.revenue_by_type.map((item) => (
                    <div
                      key={item.item_kind}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "0.6rem 0.8rem",
                        borderRadius: "0.6rem",
                        background: "rgba(20, 35, 28, 0.03)",
                        border: "1px solid var(--line)",
                      }}
                    >
                      <div className="stack" style={{ gap: "0.1rem" }}>
                        <strong style={{ textTransform: "capitalize" }}>{item.item_kind}</strong>
                        <span className="muted small">
                          {item.order_count} {item.order_count === 1 ? "order" : "orders"}
                        </span>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <strong style={{ fontSize: "1.1rem" }}>{formatCurrency(item.total_amount)}</strong>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            {/* Event Attendance Table */}
            <section className="panel stack">
              <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                <div>
                  <h2>Recent event attendance</h2>
                  <p className="muted small">Tickets checked in across recent published events.</p>
                </div>
                <Link to="/admin/events" className="small" style={{ fontWeight: 600 }}>
                  Manage events →
                </Link>
              </div>

              {data.event_attendance.length === 0 ? (
                <div className="empty">No published events found.</div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Date</th>
                      <th>Tickets</th>
                      <th>Checked In</th>
                      <th>Check-in Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.event_attendance.map((event) => {
                      const rate = typeof event.check_in_rate === "string" ? parseFloat(event.check_in_rate) : event.check_in_rate;
                      const badgeClass =
                        rate >= 75 ? "badge" : rate >= 40 ? "badge badge--warn" : "badge badge--danger";

                      return (
                        <tr key={event.event_id}>
                          <td>
                            <strong>{event.title}</strong>
                          </td>
                          <td>{formatDate(event.starts_at)}</td>
                          <td>{event.total_tickets}</td>
                          <td>{event.checked_in}</td>
                          <td>
                            <span className={badgeClass}>
                              {rate.toFixed(1)}%
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>

            {/* Recent Activity Feed */}
            <section className="panel stack">
              <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                <div>
                  <h2>Recent activity</h2>
                  <p className="muted small">Latest actions recorded in the club audit log.</p>
                </div>
                <Link to="/admin/audit" className="small" style={{ fontWeight: 600 }}>
                  View full audit log →
                </Link>
              </div>

              {data.recent_activity.length === 0 ? (
                <div className="empty">No recent activity recorded.</div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Actor</th>
                      <th>Action</th>
                      <th>Entity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_activity.map((entry) => (
                      <tr key={entry.id}>
                        <td className="small">{formatDateTime(entry.created_at)}</td>
                        <td>{entry.actor_name ?? <span className="muted">—</span>}</td>
                        <td>
                          <code>{entry.action}</code>
                        </td>
                        <td>
                          <span className="badge" style={{ background: "rgba(20, 35, 28, 0.08)", color: "var(--ink)" }}>
                            {entry.entity_type}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </div>
        )}
      </PageState>
    </div>
  );
}
