import { useEffect, useState, type FormEvent } from "react";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { EventItem } from "../../types/api";

export function AdminEventsPage() {
  const { activeClub, hasPermission } = useAuth();
  const [events, setEvents] = useState<EventItem[]>([]);
  const [title, setTitle] = useState("");
  const [venue, setVenue] = useState("Main Hall");
  const [capacity, setCapacity] = useState("50");
  const [memberPrice, setMemberPrice] = useState("100");
  const [publicPrice, setPublicPrice] = useState("200");
  const [publishNow, setPublishNow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function reload() {
    if (!activeClub) return;
    setEvents(await api.get<EventItem[]>(`/api/v1/clubs/${activeClub.club.id}/events`));
  }

  useEffect(() => {
    void reload();
  }, [activeClub]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_events")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    const starts = new Date(Date.now() + 7 * 86400000);
    const ends = new Date(starts.getTime() + 2 * 3600000);
    try {
      const event = await api.post<EventItem>(`/api/v1/clubs/${activeClub!.club.id}/events`, {
        title,
        description: "",
        venue,
        starts_at: starts.toISOString(),
        ends_at: ends.toISOString(),
        capacity: Number(capacity),
        sales_opens_at: new Date().toISOString(),
        sales_closes_at: starts.toISOString(),
      });
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/events/${event.id}/ticket-types`, {
        name: "General",
        description: "General admission",
        member_price: memberPrice,
        public_price: publicPrice,
      });
      if (publishNow) {
        await api.post(`/api/v1/clubs/${activeClub!.club.id}/events/${event.id}/status`, {
          status: "published",
        });
      }
      setTitle("");
      setMessage(
        publishNow
          ? "Event created and published."
          : "Event saved as draft. Publish it when prices look right.",
      );
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Create failed");
    }
  }

  async function setStatus(eventId: string, status: string) {
    setError(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/events/${eventId}/status`, { status });
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Manage events</h1>
        <p className="muted">Set ticket prices, save as draft, then publish when ready.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}
      <form className="panel form" onSubmit={create} style={{ maxWidth: 520 }}>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Venue
          <input value={venue} onChange={(e) => setVenue(e.target.value)} required />
        </label>
        <label>
          Capacity
          <input value={capacity} onChange={(e) => setCapacity(e.target.value)} required />
        </label>
        <div className="grid-2">
          <label>
            Member price (₹)
            <input value={memberPrice} onChange={(e) => setMemberPrice(e.target.value)} required />
          </label>
          <label>
            Public price (₹)
            <input value={publicPrice} onChange={(e) => setPublicPrice(e.target.value)} required />
          </label>
        </div>
        <label className="check-row">
          <input
            type="checkbox"
            checked={publishNow}
            onChange={(e) => setPublishNow(e.target.checked)}
          />
          Publish immediately (otherwise stays draft)
        </label>
        <button className="btn" type="submit">
          Create event
        </button>
      </form>
      <section className="panel stack">
        {events.map((ev) => {
          const member = ev.ticket_types[0]?.prices.find((p) => p.audience === "member");
          const pub = ev.ticket_types[0]?.prices.find((p) => p.audience === "public");
          return (
            <div key={ev.id} className="row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong>{ev.title}</strong> <span className="badge">{ev.status}</span>
                <div className="muted small">
                  Cap {ev.capacity} · left {ev.seats_remaining ?? "—"} · Member ₹{member?.amount ?? "—"} ·
                  Public ₹{pub?.amount ?? "—"}
                </div>
              </div>
              <div className="row">
                {ev.status === "draft" && (
                  <button
                    className="btn"
                    type="button"
                    onClick={() => void setStatus(ev.id, "published")}
                  >
                    Publish
                  </button>
                )}
                {ev.status === "published" && (
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => void setStatus(ev.id, "draft")}
                  >
                    Unpublish
                  </button>
                )}
                {ev.status !== "cancelled" && (
                  <button
                    className="btn btn--danger"
                    type="button"
                    onClick={() => void setStatus(ev.id, "cancelled")}
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
