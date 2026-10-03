import { useEffect, useState, type FormEvent } from "react";

import { Feedback, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { EventItem } from "../../types/api";

export function CheckInPage() {
  const { activeClub, hasPermission } = useAuth();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [eventId, setEventId] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeClub || !hasPermission("check_in")) return;
    api.get<EventItem[]>(`/api/v1/clubs/${activeClub.club.id}/events`).then((data) => {
      setEvents(data);
      if (data[0]) setEventId(data[0].id);
    });
  }, [activeClub, hasPermission]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("check_in")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    setError(null);
    try {
      const res = await api.post<{ status: string }>(
        `/api/v1/clubs/${activeClub!.club.id}/events/${eventId}/check-in`,
        { qr_token: token.trim() },
      );
      setMessage(`Checked in (${res.status}).`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Check-in failed");
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 560 }}>
      <div className="hero-block">
        <h1>Check-in</h1>
        <p className="muted">Enter or paste the ticket token from the attendee QR.</p>
      </div>
      {!events.length ? (
        <Spinner label="Loading events…" />
      ) : (
        <form className="panel form" onSubmit={onSubmit}>
          <label>
            Event
            <select value={eventId} onChange={(e) => setEventId(e.target.value)}>
              {events.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            QR token
            <input value={token} onChange={(e) => setToken(e.target.value)} required />
          </label>
          <button className="btn" type="submit">
            Check in
          </button>
          {message && <Feedback tone="ok">{message}</Feedback>}
          {error && <Feedback tone="danger">{error}</Feedback>}
        </form>
      )}
    </div>
  );
}
