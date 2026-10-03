import { QRCodeSVG } from "qrcode.react";
import { Link } from "react-router-dom";

import { Feedback, PageState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { statusBadgeClass } from "../../lib/format";
import { api } from "../../services/api";
export function TicketsPage() {
  const { me, loading } = useAuth();
  const ticketsRes = useAsyncResource(
    me ? () => api.get("/api/v1/me/tickets") : null,
    [me?.user.id],
    { cacheKeys: ["tickets"] },
  );

  if (loading) return <Spinner />;
  if (!me) {
    return (
      <Feedback tone="warn">
        Please <Link to="/login?next=/tickets">log in</Link>.
      </Feedback>
    );
  }

  const tickets = ticketsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>My tickets</h1>
        <p className="muted">Show the QR code at check-in.</p>
      </div>
      <PageState
        loading={ticketsRes.loading}
        error={ticketsRes.error}
        empty={tickets.length === 0}
        emptyMessage="No tickets issued."
      >
        <div className="grid-2">
          {tickets.map((ticket) => (
            <article key={ticket.id} className="panel stack">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{ticket.event_title ?? `Event ${ticket.event_id.slice(0, 8)}`}</strong>
                <span className={statusBadgeClass(ticket.status)}>{ticket.status}</span>
              </div>
              <p className="muted small">{new Date(ticket.issued_at).toLocaleString()}</p>
              {ticket.qr_token ? (
                <div className="qr-box">
                  <QRCodeSVG value={ticket.qr_token} size={160} />
                  <p className="muted small">Show this QR at check-in</p>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => void navigator.clipboard.writeText(ticket.qr_token ?? "")}
                  >
                    Copy check-in code
                  </button>
                </div>
              ) : (
                <Feedback tone="warn">QR unavailable</Feedback>
              )}
            </article>
          ))}
        </div>
      </PageState>
    </div>
  );
}
