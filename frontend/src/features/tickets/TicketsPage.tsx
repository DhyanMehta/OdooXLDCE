import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Link } from "react-router-dom";

import { Empty, Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { Ticket } from "../../types/api";

export function TicketsPage() {
  const { me, loading } = useAuth();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    api
      .get<Ticket[]>("/api/v1/me/tickets")
      .then(setTickets)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Failed to load"));
  }, [me]);

  if (loading) return <Spinner />;
  if (!me) return <Feedback tone="warn">Please <Link to="/login">log in</Link>.</Feedback>;
  if (error) return <Feedback tone="danger">{error}</Feedback>;

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>My tickets</h1>
      </div>
      {tickets.length === 0 ? (
        <Empty>No tickets issued.</Empty>
      ) : (
        <div className="grid-2">
          {tickets.map((ticket) => (
            <article key={ticket.id} className="panel stack">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{ticket.event_title ?? `Event ${ticket.event_id.slice(0, 8)}`}</strong>
                <span className="badge">{ticket.status}</span>
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
      )}
    </div>
  );
}
