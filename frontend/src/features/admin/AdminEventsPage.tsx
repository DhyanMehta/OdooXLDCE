import { useState, type FormEvent } from "react";

import { Feedback, PageState } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { fromLocalInput, statusBadgeClass, toLocalInput } from "../../lib/format";
import { clubKey, invalidate } from "../../lib/queryCache";
import { api, formatApiError } from "../../services/api";
import type { AffectedBooking, EventItem } from "../../types/api";

function defaultStarts(): string {
  const d = new Date(Date.now() + 7 * 86400000);
  return toLocalInput(d.toISOString());
}

function defaultEnds(startsLocal: string): string {
  const d = new Date(fromLocalInput(startsLocal));
  d.setHours(d.getHours() + 2);
  return toLocalInput(d.toISOString());
}

export function AdminEventsPage() {
  const { activeClub, hasPermission } = useAuth();
  const clubId = activeClub?.club.id ?? null;

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [venue, setVenue] = useState("Main Hall");
  const [capacity, setCapacity] = useState("50");
  const [startsAt, setStartsAt] = useState(defaultStarts);
  const [endsAt, setEndsAt] = useState(() => defaultEnds(defaultStarts()));
  const [salesOpens, setSalesOpens] = useState(() => toLocalInput(new Date().toISOString()));
  const [salesCloses, setSalesCloses] = useState(defaultStarts);
  const [ticketName, setTicketName] = useState("General");
  const [memberPrice, setMemberPrice] = useState("100");
  const [publicPrice, setPublicPrice] = useState("200");
  const [publishNow, setPublishNow] = useState(false);

  const [editId, setEditId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [affected, setAffected] = useState<AffectedBooking[]>([]);
  const [busy, setBusy] = useState(false);

  const eventsRes = useAsyncResource(
    clubId && hasPermission("manage_events")
      ? () =>
          api.get("/api/v1/clubs/{club_id}/events", {
            params: { path: { club_id: clubId } },
          })
      : null,
    [clubId, hasPermission("manage_events")],
    { cacheKeys: clubId ? [clubKey(clubId, "events")] : [] },
  );

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_events")) return <Feedback tone="danger">Forbidden</Feedback>;

  function resetCreate() {
    setEditId(null);
    setTitle("");
    setDescription("");
    setVenue("Main Hall");
    setCapacity("50");
    const s = defaultStarts();
    setStartsAt(s);
    setEndsAt(defaultEnds(s));
    setSalesOpens(toLocalInput(new Date().toISOString()));
    setSalesCloses(s);
    setTicketName("General");
    setMemberPrice("100");
    setPublicPrice("200");
    setPublishNow(false);
  }

  function startEdit(ev: EventItem) {
    setEditId(ev.id);
    setTitle(ev.title);
    setDescription(ev.description);
    setVenue(ev.venue);
    setCapacity(String(ev.capacity));
    setStartsAt(toLocalInput(ev.starts_at));
    setEndsAt(toLocalInput(ev.ends_at));
    setSalesOpens(toLocalInput(ev.sales_opens_at));
    setSalesCloses(toLocalInput(ev.sales_closes_at));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setAffected([]);
    setBusy(true);
    const fields = {
      title,
      description,
      venue,
      starts_at: fromLocalInput(startsAt),
      ends_at: fromLocalInput(endsAt),
      capacity: Number(capacity),
      sales_opens_at: salesOpens ? fromLocalInput(salesOpens) : null,
      sales_closes_at: salesCloses ? fromLocalInput(salesCloses) : null,
    };
    try {
      if (editId) {
        await api.patch("/api/v1/clubs/{club_id}/events/{event_id}", {
          params: { path: { club_id: activeClub!.club.id, event_id: editId } },
          body: fields,
        });
        setMessage("Event updated.");
      } else {
        await api.post("/api/v1/clubs/{club_id}/events", {
          params: { path: { club_id: activeClub!.club.id } },
          body: {
            ...fields,
            ticket_types: [
              {
                name: ticketName,
                description: "General admission",
                member_price: memberPrice,
                public_price: publicPrice,
              },
            ],
            publish: publishNow,
          },
        });
        setMessage(publishNow ? "Event created and published." : "Event saved as draft.");
      }
      resetCreate();
      invalidate(clubKey(activeClub!.club.id, "events"));
      await eventsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(eventId: string, status: string) {
    if (status === "cancelled" && !window.confirm("Cancel this event? Bookings may be affected.")) {
      return;
    }
    if (status === "published" && !window.confirm("Publish this event?")) return;
    if (status === "draft" && !window.confirm("Unpublish (move to draft)?")) return;
    setError(null);
    setMessage(null);
    try {
      const result = await api.post("/api/v1/clubs/{club_id}/events/{event_id}/status", {
        params: { path: { club_id: activeClub!.club.id, event_id: eventId } },
        body: { status },
      });
      setAffected(result.affected_bookings ?? []);
      setMessage(`Status set to ${status}.`);
      invalidate(clubKey(activeClub!.club.id, "events"));
      await eventsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  async function patchTicketType(
    eventId: string,
    ticketTypeId: string,
    fields: {
      name?: string | null;
      description?: string | null;
      is_active?: boolean | null;
      member_price?: number | string | null;
      public_price?: number | string | null;
      member_price_active?: boolean | null;
      public_price_active?: boolean | null;
    },
  ) {
    setError(null);
    try {
      await api.patch("/api/v1/clubs/{club_id}/events/{event_id}/ticket-types/{ticket_type_id}", {
        params: {
          path: {
            club_id: activeClub!.club.id,
            event_id: eventId,
            ticket_type_id: ticketTypeId,
          },
        },
        body: fields,
      });
      invalidate(clubKey(activeClub!.club.id, "events"));
      await eventsRes.reload();
    } catch (err) {
      setError(formatApiError(err));
    }
  }

  const events = eventsRes.data ?? [];

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Manage events</h1>
        <p className="muted">Schedule, ticket types, and publish atomically on create.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      {message && <Feedback tone="ok">{message}</Feedback>}
      {affected.length > 0 && (
        <section className="panel stack">
          <h2>Affected bookings</h2>
          <table>
            <thead>
              <tr>
                <th>Buyer</th>
                <th>Order</th>
                <th>Status</th>
                <th>Tickets</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {affected.map((b) => (
                <tr key={`${b.order_id}-${b.reason}`}>
                  <td>
                    {b.user_name ?? "—"}
                    <div className="muted small">{b.user_email}</div>
                  </td>
                  <td className="mono">{b.order_id.slice(0, 8)}</td>
                  <td>
                    <span className={statusBadgeClass(b.order_status)}>{b.order_status}</span>
                  </td>
                  <td>{b.ticket_count}</td>
                  <td className="muted small">{b.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <form className="panel form" onSubmit={onSubmit} style={{ maxWidth: 560 }}>
        <h2>{editId ? "Edit event" : "Create event"}</h2>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Description
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
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
            Starts
            <input
              type="datetime-local"
              value={startsAt}
              onChange={(e) => {
                setStartsAt(e.target.value);
                setEndsAt(defaultEnds(e.target.value));
              }}
              required
            />
          </label>
          <label>
            Ends
            <input
              type="datetime-local"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              required
            />
          </label>
        </div>
        <div className="grid-2">
          <label>
            Sales open
            <input
              type="datetime-local"
              value={salesOpens}
              onChange={(e) => setSalesOpens(e.target.value)}
            />
          </label>
          <label>
            Sales close
            <input
              type="datetime-local"
              value={salesCloses}
              onChange={(e) => setSalesCloses(e.target.value)}
            />
          </label>
        </div>
        {!editId && (
          <>
            <label>
              Ticket type name
              <input value={ticketName} onChange={(e) => setTicketName(e.target.value)} required />
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
              Publish immediately
            </label>
          </>
        )}
        <div className="row">
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving…" : editId ? "Save event" : "Create event"}
          </button>
          {editId && (
            <button className="btn btn--ghost" type="button" onClick={resetCreate}>
              Cancel edit
            </button>
          )}
        </div>
      </form>

      <PageState
        loading={eventsRes.loading}
        error={eventsRes.error}
        empty={events.length === 0}
        emptyMessage="No events yet."
      >
        <section className="panel stack">
          {events.map((ev) => {
            const member = ev.ticket_types[0]?.prices.find((p) => p.audience === "member");
            const pub = ev.ticket_types[0]?.prices.find((p) => p.audience === "public");
            return (
              <div key={ev.id} className="stack" style={{ borderBottom: "1px solid var(--line)", paddingBottom: "0.75rem" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <strong>{ev.title}</strong>{" "}
                    <span className={statusBadgeClass(ev.status)}>{ev.status}</span>
                    <div className="muted small">
                      {new Date(ev.starts_at).toLocaleString()} · Cap {ev.capacity} · left{" "}
                      {ev.seats_remaining ?? "—"} · Member ₹{member?.amount ?? "—"} · Public ₹
                      {pub?.amount ?? "—"}
                    </div>
                  </div>
                  <div className="row">
                    <button className="btn btn--ghost" type="button" onClick={() => startEdit(ev)}>
                      Edit
                    </button>
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
                {ev.ticket_types.map((tt) => (
                  <div key={tt.id} className="row" style={{ justifyContent: "space-between" }}>
                    <span className="muted small">
                      Ticket: {tt.name}{" "}
                      {tt.is_active === false && (
                        <span className="badge badge--warn">disabled</span>
                      )}
                    </span>
                    <div className="row">
                      <button
                        className="btn btn--ghost"
                        type="button"
                        onClick={() => {
                          const nextName = window.prompt("Ticket type name", tt.name);
                          if (nextName && nextName !== tt.name) {
                            void patchTicketType(ev.id, tt.id, { name: nextName });
                          }
                        }}
                      >
                        Rename
                      </button>
                      <button
                        className="btn btn--ghost"
                        type="button"
                        onClick={() =>
                          void patchTicketType(ev.id, tt.id, {
                            is_active: tt.is_active === false,
                          })
                        }
                      >
                        {tt.is_active === false ? "Enable" : "Disable"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      </PageState>
    </div>
  );
}
