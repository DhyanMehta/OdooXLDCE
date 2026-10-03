import { useEffect, useState, type FormEvent } from "react";

import { Feedback } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { api, ApiError } from "../../services/api";
import type { Announcement } from "../../types/api";

export function AdminAnnouncementsPage() {
  const { activeClub, hasPermission } = useAuth();
  const [items, setItems] = useState<Announcement[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("public");
  const [error, setError] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<unknown[]>([]);

  async function reload() {
    if (!activeClub) return;
    setItems(await api.get<Announcement[]>(`/api/v1/clubs/${activeClub.club.id}/announcements`));
  }

  useEffect(() => {
    void reload();
  }, [activeClub]);

  if (!activeClub) return <Feedback tone="warn">Select a club.</Feedback>;
  if (!hasPermission("manage_announcements")) return <Feedback tone="danger">Forbidden</Feedback>;

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/announcements`, {
        title,
        body,
        visibility,
      });
      setTitle("");
      setBody("");
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Create failed");
    }
  }

  async function publish(id: string) {
    setError(null);
    try {
      await api.post(`/api/v1/clubs/${activeClub!.club.id}/announcements/${id}/publish`);
      const d = await api.get<unknown[]>(
        `/api/v1/clubs/${activeClub!.club.id}/announcements/${id}/deliveries`,
      );
      setDeliveries(d);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publish failed");
    }
  }

  return (
    <div className="stack">
      <div className="hero-block">
        <h1>Announcements</h1>
        <p className="muted">Publish queues email deliveries transactionally; worker marks them simulated.</p>
      </div>
      {error && <Feedback tone="danger">{error}</Feedback>}
      <form className="panel form" onSubmit={create}>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Body
          <textarea value={body} onChange={(e) => setBody(e.target.value)} required />
        </label>
        <label>
          Visibility
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="public">Public</option>
            <option value="members">Members only</option>
          </select>
        </label>
        <button className="btn" type="submit">
          Save draft
        </button>
      </form>
      <section className="panel stack">
        {items.map((item) => (
          <div key={item.id} className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <strong>{item.title}</strong>{" "}
              <span className="badge">{item.status}</span>{" "}
              <span className="muted small">{item.visibility}</span>
            </div>
            {item.status !== "published" && (
              <button className="btn" type="button" onClick={() => void publish(item.id)}>
                Publish
              </button>
            )}
          </div>
        ))}
      </section>
      {deliveries.length > 0 && (
        <section className="panel stack">
          <h2>Delivery status</h2>
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(deliveries as Array<{ recipient_email: string; status: string }>).map((d, i) => (
                <tr key={`${d.recipient_email}-${i}`}>
                  <td>{d.recipient_email}</td>
                  <td>
                    <span className="badge">{d.status.replaceAll("_", " ")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
